"""Shared utilities for all Blender handlers."""
import bpy
from contextlib import contextmanager


@contextmanager
def ensure_object_mode(obj):
    """Switch to OBJECT mode, yield, then restore. Context manager."""
    prev_mode = None
    prev_active = bpy.context.view_layer.objects.active

    if obj and obj.mode != 'OBJECT':
        prev_mode = obj.mode
        bpy.context.view_layer.objects.active = obj
        bpy.ops.object.mode_set(mode='OBJECT')

    try:
        yield
    finally:
        if prev_mode and obj:
            bpy.context.view_layer.objects.active = obj
            try:
                bpy.ops.object.mode_set(mode=prev_mode)
            except RuntimeError:
                pass
        if prev_active:
            bpy.context.view_layer.objects.active = prev_active


@contextmanager
def ensure_edit_mode(obj):
    """Select, activate, enter EDIT mode, select all mesh. Context manager."""
    prev_mode = None
    prev_active = bpy.context.view_layer.objects.active

    if obj:
        prev_mode = obj.mode
        select_only(obj)
        if obj.mode != 'EDIT':
            bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')

    try:
        yield
    finally:
        if obj and obj.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        if prev_mode and prev_mode != 'EDIT' and obj:
            bpy.context.view_layer.objects.active = obj
            try:
                bpy.ops.object.mode_set(mode=prev_mode)
            except RuntimeError:
                pass
        if prev_active:
            bpy.context.view_layer.objects.active = prev_active


def select_only(obj):
    """Deselect all, select and activate obj."""
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def require_mesh(obj_or_name):
    """Validate obj exists and is MESH type. Returns (obj, error_dict_or_None)."""
    if isinstance(obj_or_name, str):
        obj = bpy.data.objects.get(obj_or_name)
        if not obj:
            return None, {"error": f"Object not found: {obj_or_name}"}
    else:
        obj = obj_or_name
    if obj.type != 'MESH':
        return None, {"error": f"Object '{obj.name}' is not a MESH (type={obj.type})"}
    return obj, None


def set_properties_safe(target, props):
    """Set attributes on target with error collection.

    Returns:
        (set_props, failed_props) where failed_props is list of {name, error} dicts
    """
    set_props = []
    failed_props = []
    for prop_name, value in props.items():
        if not hasattr(target, prop_name):
            failed_props.append({"name": prop_name, "error": "attribute not found"})
            continue
        try:
            setattr(target, prop_name, value)
            set_props.append(prop_name)
        except Exception as e:
            failed_props.append({"name": prop_name, "error": str(e)})
    return set_props, failed_props


def compute_world_aabb(obj):
    """Compute world-space AABB for any object type.

    For MESH objects, uses actual vertex bounds via bound_box.
    For hierarchies (e.g. Sketchfab imports), traverses all MESH descendants.
    Returns (aabb_min, aabb_max, aabb_center) as mathutils.Vectors,
    or (None, None, None) if no geometry found.
    """
    import mathutils

    def _collect_mesh_bounds(obj):
        """Collect world-space bbox corners from obj and all MESH descendants."""
        corners = []
        if obj.type == 'MESH' and obj.data:
            for c in obj.bound_box:
                corners.append(obj.matrix_world @ mathutils.Vector(c))
        for child in obj.children:
            corners.extend(_collect_mesh_bounds(child))
        return corners

    corners = _collect_mesh_bounds(obj)
    if not corners:
        return None, None, None

    aabb_min = mathutils.Vector((
        min(c.x for c in corners),
        min(c.y for c in corners),
        min(c.z for c in corners),
    ))
    aabb_max = mathutils.Vector((
        max(c.x for c in corners),
        max(c.y for c in corners),
        max(c.z for c in corners),
    ))
    aabb_center = (aabb_min + aabb_max) / 2
    return aabb_min, aabb_max, aabb_center


def rotation_to_compass(rotation_z_deg):
    """Convert Z-rotation in degrees to compass direction (N/NE/E/SE/S/SW/W/NW).

    Convention: 0deg = -Y forward = North.
    """
    angle = rotation_z_deg % 360
    # 8 compass directions, 45deg each, centered
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    index = int((angle + 22.5) / 45) % 8
    return directions[index]


class SpatialGrid:
    """Uniform spatial grid for O(1) neighbor queries.

    Divides world space into cells of `cell_size` meters. Objects are inserted
    by their AABB center. Neighbor queries return objects in the same cell and
    all 26 adjacent cells (3x3x3 neighborhood).

    Turns O(n^2) pairwise checks into O(n * k) where k = avg objects per
    neighborhood. For a 10m room with 2m cells: 125 cells, ~1 object per cell.
    For open world with 10k objects: still O(n * k) with k << n.
    """

    def __init__(self, cell_size=2.0):
        self.cell_size = cell_size
        self._cells = {}  # (cx, cy, cz) -> [(obj, data), ...]

    def _cell_key(self, x, y, z):
        return (
            int(x // self.cell_size),
            int(y // self.cell_size),
            int(z // self.cell_size),
        )

    def insert(self, obj, data, center):
        """Insert an object at its AABB center position."""
        key = self._cell_key(center[0], center[1], center[2])
        self._cells.setdefault(key, []).append((obj, data))

    def neighbors(self, center, radius=None):
        """Return all objects in the neighborhood of a position.

        If radius is None, returns 3x3x3 cell neighborhood (26 adjacent + self).
        If radius is set, returns all cells within that radius.
        """
        cx, cy, cz = self._cell_key(center[0], center[1], center[2])
        if radius is not None:
            r_cells = int(radius / self.cell_size) + 1
        else:
            r_cells = 1
        result = []
        for dx in range(-r_cells, r_cells + 1):
            for dy in range(-r_cells, r_cells + 1):
                for dz in range(-r_cells, r_cells + 1):
                    key = (cx + dx, cy + dy, cz + dz)
                    result.extend(self._cells.get(key, []))
        return result

    def nearby_pairs(self):
        """Yield all (obj_a, data_a, obj_b, data_b) pairs that share a cell neighborhood.

        Each pair yielded exactly once (no duplicates). O(n * k) total.
        """
        seen_pairs = set()
        for key, items in self._cells.items():
            # Get all objects in this cell + adjacent cells
            cx, cy, cz = key
            neighborhood = []
            for dx in range(-1, 2):
                for dy in range(-1, 2):
                    for dz in range(-1, 2):
                        nkey = (cx + dx, cy + dy, cz + dz)
                        neighborhood.extend(self._cells.get(nkey, []))

            # Emit pairs between this cell's items and the full neighborhood
            for obj_a, data_a in items:
                for obj_b, data_b in neighborhood:
                    if obj_a == obj_b:
                        continue
                    pair = frozenset((id(obj_a), id(obj_b)))
                    if pair in seen_pairs:
                        continue
                    seen_pairs.add(pair)
                    yield obj_a, data_a, obj_b, data_b


def compute_obb_overlap(obj_a, obj_b):
    """SAT (Separating Axis Theorem) test on oriented bounding boxes.

    Uses Blender's local-space bound_box × matrix_world for oriented axes.
    Tests 15 separating axes: 3 from A, 3 from B, 9 cross products.
    Returns True if OBBs overlap, False if separated.
    """
    import mathutils

    def _obb_data(obj):
        """Extract OBB center, half-extents, and 3 oriented axes from object."""
        bb = obj.bound_box  # 8 corners in local space
        # Local AABB min/max
        lmin = mathutils.Vector((min(c[0] for c in bb), min(c[1] for c in bb), min(c[2] for c in bb)))
        lmax = mathutils.Vector((max(c[0] for c in bb), max(c[1] for c in bb), max(c[2] for c in bb)))
        local_center = (lmin + lmax) / 2
        half = (lmax - lmin) / 2

        mw = obj.matrix_world
        center = mw @ local_center

        # Extract rotation axes from matrix_world (first 3 columns, normalized)
        axes = []
        for i in range(3):
            col = mathutils.Vector((mw[0][i], mw[1][i], mw[2][i]))
            length = col.length
            if length < 1e-9:
                axes.append(mathutils.Vector((1 if i == 0 else 0, 1 if i == 1 else 0, 1 if i == 2 else 0)))
                half[i] = 0
            else:
                axes.append(col / length)
                half[i] *= length  # scale half-extents by axis scale

        return center, half, axes

    try:
        c_a, h_a, ax_a = _obb_data(obj_a)
        c_b, h_b, ax_b = _obb_data(obj_b)
    except Exception:
        return True  # Can't compute — assume overlap (conservative)

    T = c_b - c_a  # Vector from A center to B center

    def _separated(axis):
        """Check if axis is a separating axis. Returns True if separated."""
        length = axis.length
        if length < 1e-9:
            return False  # Degenerate axis, skip
        axis = axis / length

        # Project half-extents of both OBBs onto axis
        ra = sum(abs(ax_a[i].dot(axis)) * h_a[i] for i in range(3))
        rb = sum(abs(ax_b[i].dot(axis)) * h_b[i] for i in range(3))
        dist = abs(T.dot(axis))
        return dist > ra + rb + 1e-6

    # Test 3 axes from A
    for a in ax_a:
        if _separated(a):
            return False
    # Test 3 axes from B
    for b in ax_b:
        if _separated(b):
            return False
    # Test 9 cross product axes
    for a in ax_a:
        for b in ax_b:
            cross = a.cross(b)
            if _separated(cross):
                return False

    return True  # No separating axis found — OBBs overlap


class Octree:
    """Adaptive spatial index — subdivides dense regions, stays coarse in sparse areas.

    Better than uniform SpatialGrid for non-uniform object density (e.g.,
    dense furniture cluster in one corner of a large room).

    Subdivides cells exceeding max_items, down to min_cell_size.
    API-compatible with SpatialGrid for drop-in replacement.
    """

    def __init__(self, bounds_min, bounds_max, max_items=8, min_cell_size=0.5, _depth=0):
        self.bounds_min = bounds_min  # [x, y, z]
        self.bounds_max = bounds_max  # [x, y, z]
        self.max_items = max_items
        self.min_cell_size = min_cell_size
        self._depth = _depth
        self._items = []  # [(obj, data, center)]
        self._children = None  # 8 child octants when subdivided
        self._all_items = []  # flat list for nearby_pairs (root only)

    @classmethod
    def from_objects(cls, mesh_objects, max_items=8, min_cell_size=0.5):
        """Build Octree from list of (obj, obj_data) pairs. Auto-computes bounds."""
        if not mesh_objects:
            # Return empty tree
            return cls([0, 0, 0], [1, 1, 1], max_items, min_cell_size)

        centers = []
        for obj, data in mesh_objects:
            wc = data.get("world_center", [0, 0, 0])
            centers.append(wc)

        # Compute bounds with padding
        pad = 1.0
        bmin = [min(c[i] for c in centers) - pad for i in range(3)]
        bmax = [max(c[i] for c in centers) + pad for i in range(3)]

        # Ensure minimum size
        for i in range(3):
            if bmax[i] - bmin[i] < 2.0:
                mid = (bmin[i] + bmax[i]) / 2
                bmin[i] = mid - 1.0
                bmax[i] = mid + 1.0

        tree = cls(bmin, bmax, max_items, min_cell_size)
        for obj, data in mesh_objects:
            wc = data.get("world_center", [0, 0, 0])
            tree.insert(obj, data, wc)
        return tree

    def _subdivide(self):
        """Split this node into 8 children."""
        mid = [(self.bounds_min[i] + self.bounds_max[i]) / 2 for i in range(3)]
        self._children = []
        for i in range(8):
            cmin = [
                mid[0] if (i & 1) else self.bounds_min[0],
                mid[1] if (i & 2) else self.bounds_min[1],
                mid[2] if (i & 4) else self.bounds_min[2],
            ]
            cmax = [
                self.bounds_max[0] if (i & 1) else mid[0],
                self.bounds_max[1] if (i & 2) else mid[1],
                self.bounds_max[2] if (i & 4) else mid[2],
            ]
            self._children.append(
                Octree(cmin, cmax, self.max_items, self.min_cell_size, self._depth + 1)
            )
        # Re-insert existing items into children
        for item in self._items:
            self._insert_into_child(item)
        self._items = []

    def _child_index(self, center):
        """Determine which octant a point falls into."""
        mid = [(self.bounds_min[i] + self.bounds_max[i]) / 2 for i in range(3)]
        idx = 0
        if center[0] >= mid[0]:
            idx |= 1
        if center[1] >= mid[1]:
            idx |= 2
        if center[2] >= mid[2]:
            idx |= 4
        return idx

    def _insert_into_child(self, item):
        """Insert item tuple into appropriate child."""
        _, _, center = item
        idx = self._child_index(center)
        self._children[idx].insert(item[0], item[1], center)

    def insert(self, obj, data, center):
        """Insert an object at its center position."""
        # Track in flat list at root level
        if self._depth == 0:
            self._all_items.append((obj, data))

        if self._children is not None:
            self._insert_into_child((obj, data, center))
            return

        self._items.append((obj, data, center))

        # Check if we need to subdivide
        cell_size = min(self.bounds_max[i] - self.bounds_min[i] for i in range(3))
        if len(self._items) > self.max_items and cell_size > self.min_cell_size * 2:
            self._subdivide()

    def _contains_point(self, center):
        """Check if point is within this node's bounds."""
        for i in range(3):
            if center[i] < self.bounds_min[i] or center[i] > self.bounds_max[i]:
                return False
        return True

    def _intersects_sphere(self, center, radius):
        """Check if this node's AABB intersects a sphere."""
        # Find closest point on AABB to sphere center
        dist_sq = 0
        for i in range(3):
            if center[i] < self.bounds_min[i]:
                dist_sq += (center[i] - self.bounds_min[i]) ** 2
            elif center[i] > self.bounds_max[i]:
                dist_sq += (center[i] - self.bounds_max[i]) ** 2
        return dist_sq <= radius * radius

    def query_radius(self, center, radius):
        """Return all (obj, data) within radius of center."""
        results = []
        if not self._intersects_sphere(center, radius):
            return results

        if self._children is not None:
            for child in self._children:
                results.extend(child.query_radius(center, radius))
        else:
            r_sq = radius * radius
            for obj, data, c in self._items:
                d_sq = sum((center[i] - c[i]) ** 2 for i in range(3))
                if d_sq <= r_sq:
                    results.append((obj, data))
        return results

    def neighbors(self, center, radius=None):
        """SpatialGrid-compatible API. Returns nearby (obj, data) pairs.

        If radius is None, uses a default neighborhood size based on cell size.
        """
        if radius is None:
            # Use a reasonable default — approximate the 3x3x3 cell neighborhood
            # of a uniform grid with cell_size=2.0
            radius = 6.0
        return self.query_radius(center, radius)

    def nearby_pairs(self):
        """Yield all (obj_a, data_a, obj_b, data_b) pairs in local neighborhoods.

        Uses the flat item list and queries neighbors for each item.
        Each pair yielded exactly once.
        """
        seen_pairs = set()
        for obj_a, data_a in self._all_items:
            wc = data_a.get("world_center", [0, 0, 0])
            for obj_b, data_b in self.query_radius(wc, 6.0):
                if obj_a is obj_b:
                    continue
                pair = frozenset((id(obj_a), id(obj_b)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                yield obj_a, data_a, obj_b, data_b
