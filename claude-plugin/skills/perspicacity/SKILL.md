---
name: perspicacity
description: Perspicacity scene perception DSL — structured 3D spatial awareness for AI. Reference for reading and reasoning about .picacia format output.
---

## Overview

Perspicacity is a structured scene perception format (.picacia). Each line starts with a prefix tag identifying its type. Objects are depth-sorted front-to-back from the camera. All directions are camera-relative. The format is UTF-8 text, one record per line.

## Output Order

BlenderWeave emits sections in this order:

1. **Critical** — VERIFY failures + critical SPATIAL facts (no_light_sources, surface_intersect)
2. **Header** — SCENE summary, CAM, WORLD, FOCUS
3. **Lights** — LIGHT lines
4. **Objects** — OBJ + SGROUP lines (depth-sorted, budget-capped)
5. **Spatial Layout** — MVIEW, COMP, REL
6. **Appearance** — LIT, SHAD, MAT, HARMONY, PALETTE
7. **Spatial Facts** — SPATIAL lines (non-critical, sorted by priority)
8. **Assemblies** — ASSEMBLY lines
9. **Structure** — HIER, GRP, CONTAIN, PHYS, ANIM
10. **Coverage** — RAY grid

---

## Line Types Reference

### 1. SCENE — Scene Header

**Prefix:** `SCENE`
**Format:** `SCENE <obj_count> objects <light_count> lights <energy>W <engine> [ground_z=<N>]`

| Field       | Type   | Req/Opt  | Description                      |
|-------------|--------|----------|----------------------------------|
| obj_count   | int    | required | Total visible object count       |
| light_count | int    | required | Total light count                |
| energy      | float  | required | Total light energy in watts      |
| engine      | string | required | Render engine name               |
| ground_z    | float  | optional | Detected ground plane Z level    |

**Example:**
```
SCENE 42 objects 3 lights 1200W BLENDER_EEVEE ground_z=0.0
```

---

### 2. CAM — Camera

**Prefix:** `CAM`
**Format:** `CAM <name> <position> <focal> [fov=<N>°]`

| Field    | Type   | Req/Opt  | Description                  |
|----------|--------|----------|------------------------------|
| name     | string | required | Camera name                  |
| position | Vec3   | required | World-space position         |
| focal    | Nmm    | required | Focal length in millimeters  |
| fov      | N°     | optional | Field of view in degrees     |

**Example:**
```
CAM PlayerCam [0,2,8] 35mm fov=54°
```

**Reasoning:** Establishes the viewpoint. Focal length affects field of view — lower mm = wider angle, higher mm = telephoto. Position combined with OBJ depths gives you the spatial layout of the scene.

---

### 3. FOCUS — Perception Focus

**Prefix:** `FOCUS`
**Format:** `FOCUS [x,y,z] radius=<N>m near=<N> mid=<N> far=<N> out=<N>`

| Field  | Type   | Req/Opt  | Description                          |
|--------|--------|----------|--------------------------------------|
| center | Vec3   | required | Focus center position                |
| radius | Nm     | required | Perception radius in meters          |
| near   | int    | required | Objects in near zone                 |
| mid    | int    | required | Objects in mid zone                  |
| far    | int    | required | Objects in far zone                  |
| out    | int    | required | Objects outside perception radius    |

**Example:**
```
FOCUS [0,0,1.5] radius=8m near=5 mid=12 far=3 out=2
```

**Reasoning:** Shows the spatial focus of perception. Near/mid/far classify objects by distance from focus center. Objects marked `out` are beyond the perception radius and receive reduced analysis.

---

### 4. LIGHT — Light Source

**Prefix:** `LIGHT`
**Format:** `LIGHT <name> <type> <energy> <color> <position> [spot_props] [area_props] [noshadow]`

| Field      | Type   | Req/Opt  | Description                                      |
|------------|--------|----------|--------------------------------------------------|
| name       | string | required | Light name                                       |
| type       | enum   | required | POINT, SUN, SPOT, AREA                           |
| energy     | NW     | required | Energy in watts                                  |
| color      | Vec3   | required | RGB color [r,g,b], each 0.0-1.0                 |
| position   | Vec3   | required | World-space position                             |
| cone=N     | N°     | optional | Spot cone angle (SPOT only)                      |
| blend=N    | float  | optional | Spot edge softness 0-1 (SPOT only)               |
| area_shape | string | optional | square, rectangle, disk, ellipse (AREA only)     |
| area_size  | Nm     | optional | Area dimensions NmxNm or Nm (AREA only)          |
| noshadow   | flag   | optional | Shadow casting disabled                          |

**Examples:**
```
LIGHT Overhead AREA 800W [1,0.98,0.95] [0,5,0]
LIGHT Spot1 SPOT 300W [1,0.9,0.8] [4,3,2] cone=45° blend=0.15
LIGHT Fill POINT 100W [1,1,1] [-3,2,1] noshadow
```

**Reasoning:** Tells you what illuminates the scene. Color temperature (warm = orange-ish RGB, cool = blue-ish) affects mood. Energy and type determine falloff behavior. Cross-reference with LIT lines to see how each light affects each surface.

---

### 5. OBJ — Object

**Prefix:** `OBJ`
**Format:** `OBJ <name> <position> <coverage%> <quadrant> d=<depth> <material> [dim=<w,h,d>m] [top=<N>] [src=<source>] [rot=<rx,ry,rz>] [facing=<dir>] [toward=<name>] [away_from=<name>] [zone=<name>] [face=<dir>] [lum=<N>] [flags...]`

| Field    | Type   | Req/Opt  | Description                                          |
|----------|--------|----------|------------------------------------------------------|
| name     | string | required | Object name                                          |
| position | Vec3   | required | Mesh AABB center world-space position                |
| coverage | N%     | required | Screen-space coverage percentage                     |
| quadrant | string | required | Frame grid position (top/mid/bot)-(left/center/right)|
| depth    | d=Nm   | required | Distance from camera                                 |
| material | string | required | Material with properties in parens                   |
| dim      | Vec3m  | optional | World-space bounding box dimensions [w,h,d]m         |
| top      | float  | optional | Top Z coordinate of bounding box                     |
| src      | string | optional | Source/origin (quoted if contains spaces)             |
| rot      | Vec3   | optional | Euler rotation in degrees (only when > 1°)           |
| facing   | dir    | optional | Compass direction (N/NE/E/SE/S/SW/W/NW)             |
| toward   | string | optional | Object this one faces toward                         |
| away_from| string | optional | Object this one faces away from                      |
| zone     | string | optional | Spatial zone name                                    |
| face     | dir    | optional | Most visible face direction (+X,-X,+Y,-Y,+Z,-Z)     |
| lum      | float  | optional | Rendered luminance (0.0-1.0)                         |
| flags    | various| optional | transparent, no_uv, has_uv, flipped_normals=N%, non_manifold=N, inside=Name, contains:[names] |

**Material format:** `ColorName(key=val,key=val)` or `ColorName(textured)`
Common keys: `metal=N`, `rough=N`, `ior=N`, `emit=N`

**Examples:**
```
OBJ Crate_A [1,0.5,2] 12% mid-right d=6.3m dark_brown(rough=0.8) dim=[0.5,0.5,0.5] top=0.75 facing=NW
OBJ Floor [0,0,0] 30% bot-center d=8.5m grey(textured) dim=[10,10,0.1]
OBJ Bottle [2,1,1] 3% mid-right d=5m clear glass(rough=0.05,ior=1.5) lum=0.6 transparent
```

**Reasoning:** The core scene inventory. Objects are sorted front-to-back by depth, so the first OBJ line is the closest object to camera. Coverage tells you visual importance — higher % = more screen space. Quadrant tells you where in the frame it sits. `lum=` gives rendered luminance — low values mean the object appears dark. `facing=` is an objective compass direction derived from Z-rotation.

---

### 6. SGROUP — Semantic Group

**Prefix:** `SGROUP`
**Format:** `SGROUP "<name>" [x,y,z] dim=[w,h,d] top=<N> <material> facing=<DIR> members=<N>`

| Field    | Type   | Req/Opt  | Description                                    |
|----------|--------|----------|------------------------------------------------|
| name     | string | required | Group display name (always quoted)              |
| position | Vec3   | required | Group center position                           |
| dim      | Vec3m  | required | Group bounding box dimensions                   |
| top      | float  | required | Top Z coordinate                                |
| material | string | optional | Representative material                         |
| facing   | dir    | optional | Common facing direction of members              |
| members  | int    | required | Number of member objects (suppressed from OBJ)  |

**Example:**
```
SGROUP "Dining Chairs" [2,1,0.4] dim=[3,2,0.8] top=0.8 wood facing=N members=4
```

**Reasoning:** Groups similar objects (e.g., 4 identical chairs from same Sketchfab model) into a single line. Member objects are suppressed from individual OBJ lines to reduce noise. The group's position and dimensions represent the combined bounding box.

---

### 7. REL — Spatial Relationship

**Prefix:** `REL`
**Format:** `REL <from>→<to> <distance> <direction> [vertical] [overlap[=N%]] [aabb_overlap=N%] [contact] [occludes] [occ=N%]`

| Field    | Type   | Req/Opt  | Description                                          |
|----------|--------|----------|------------------------------------------------------|
| from     | string | required | Source object name                                   |
| to       | string | required | Target object name                                   |
| distance | Nm     | required | Distance between objects in meters                   |
| direction| string | required | Camera-relative direction (left, right, above, below, in_front, behind) |
| vertical | string | optional | Vertical relation: same_level, above, below          |
| overlap  | flag/N%| optional | Screen-space overlap, optionally with percentage     |
| aabb_overlap | N% | optional | World-space AABB overlap (camera-independent)        |
| contact  | flag   | optional | Objects are in physical contact                      |
| occludes | flag   | optional | Source occludes target from camera                    |
| occ      | occ=N% | optional | Occlusion percentage                                 |

**Examples:**
```
REL Crate_A→Crate_B 1m below contact
REL Crate_A→Barrel 3.2m left same_level
REL Rifle→Guard 0.3m right same_level
```

**Reasoning:** Pairwise spatial queries. "Crate_A→Crate_B 1m below contact" means Crate_A is 1m below Crate_B and they are touching. Direction is always camera-relative: "left" means Barrel is to the left of Crate_A from the camera's perspective. Use these to answer questions like "what is next to X?" or "is Y touching Z?".

---

### 8. LIT — Light-Surface Analysis

**Prefix:** `LIT`
**Format:** `LIT <light>→<surface> @<angle>° i=<intensity> [eff=<N>] [raw=<N>] [shadow:<casters>]`

| Field     | Type       | Req/Opt  | Description                                 |
|-----------|------------|----------|---------------------------------------------|
| light     | string     | required | Light name                                  |
| surface   | string     | required | Receiving surface name                      |
| angle     | N°         | required | Incidence angle in degrees                  |
| intensity | i=N        | required | Normalized intensity 0.0-1.0               |
| raw       | raw=N      | optional | Absolute intensity (energy x cos / dist^2)  |
| shadow    | shadow:N,N | optional | Shadow caster names                         |

**Examples:**
```
LIT Overhead→Crate_A @15° i=0.9
LIT Spot1→Forklift @35° i=0.6
LIT Spot1→Crate_A @50° i=0.4
```

**Reasoning:** Shows how each light illuminates each surface. Low angle = direct overhead/front lighting (bright). High angle = grazing light (dimmer, more shadow). Intensity i=1.0 is the brightest surface in the scene. If shadow casters are listed, those objects cast shadows onto this surface from this light.

---

### 9. SHAD — Shadow Footprint

**Prefix:** `SHAD`
**Format:** `SHAD <light>→<surface> <coverage%> [casters:<names>] [contact|gap=<Nm>]`

| Field    | Type       | Req/Opt  | Description                              |
|----------|------------|----------|------------------------------------------|
| light    | string     | required | Light name                               |
| surface  | string     | required | Surface receiving shadow                 |
| coverage | N%         | required | Shadow coverage percentage on surface    |
| casters  | casters:N  | optional | Objects casting the shadow               |
| contact  | flag       | optional | Shadow touches the caster (contact shadow)|
| gap      | gap=Nm     | optional | Gap between caster and surface           |

**Examples:**
```
SHAD Overhead→Floor 8% casters:Crate_A,Crate_B,Barrel contact
SHAD Spot1→Floor 5% casters:Forklift gap=0.1m
```

**Reasoning:** Contact shadows (gap=0, "contact" flag) ground objects and look natural. A gap means the object is floating or elevated. High coverage% means large shadow areas. Useful for checking visual grounding and lighting realism.

---

### 10. MAT — Material Prediction

**Prefix:** `MAT`
**Format:** `MAT <name>: <appearance> [-- <note>]` or `MAT <name>: UNREADABLE(<reason>)`

| Field      | Type   | Req/Opt  | Description                            |
|------------|--------|----------|----------------------------------------|
| name       | string | required | Material name                          |
| appearance | string | required | Visual description of the material     |
| note       | string | optional | Needs or warnings (after -- separator) |
| UNREADABLE | string | optional | Why the material cannot be evaluated   |

**Examples:**
```
MAT Wood: warm brown rough wood
MAT Metal: dark metallic -- needs env reflections
MAT Brick: red brick wall -- needs normal map
MAT Broken: UNREADABLE(no UV, tiling error)
```

**Reasoning:** Quick material quality check. The appearance string describes what the material looks like. Notes after `--` flag issues: "needs env reflections" means the material will look wrong without environment mapping. UNREADABLE means the material is broken and cannot be visually evaluated at all.

---

### 11. HARMONY — Material Distribution

**Prefix:** `HARMONY`
**Format:** `HARMONY types=<distribution> temp=<temperature>`

| Field | Type   | Req/Opt  | Description                              |
|-------|--------|----------|------------------------------------------|
| types | string | required | Material type distribution (e.g., "wood+metal+glass") |
| temp  | string | required | Color temperature (warm/cool/neutral/mixed) |

**Example:**
```
HARMONY types=wood+metal+concrete temp=warm
```

**Reasoning:** Summary of material variety and color temperature across the scene. Helps assess visual coherence.

---

### 12. PALETTE — Scene Colors

**Prefix:** `PALETTE`
**Format:** `PALETTE [lum=<N>] <color1> <color2> ...`

| Field   | Type   | Req/Opt  | Description                          |
|---------|--------|----------|--------------------------------------|
| lum     | float  | optional | Overall rendered luminance (0.0-1.0) |
| colors  | strings| required | Dominant scene color names           |

**Example:**
```
PALETTE lum=0.45 dark_brown warm_grey soft_white
```

**Reasoning:** Derived from micro-render analysis. Shows dominant colors and overall brightness. Low lum values suggest underlit scenes.

---

### 13. WORLD — World Environment

**Prefix:** `WORLD`
**Format:** `WORLD bg=<color> strength=<N>` or `WORLD hdri strength=<N>`

| Field    | Type   | Req/Opt  | Description                    |
|----------|--------|----------|--------------------------------|
| bg       | Vec3   | optional | Background RGB color 0.0-1.0   |
| hdri     | flag   | optional | HDRI environment map is active |
| strength | float  | required | Environment strength           |

**Examples:**
```
WORLD bg=[0.02,0.02,0.03] strength=0.5
WORLD hdri strength=1.0
```

**Reasoning:** Dark bg with low strength = indoor/studio feel. HDRI = realistic environment lighting and reflections. Metallic materials need HDRI or environment to look correct (cross-reference with MAT "needs env reflections" warnings).

---

### 14. COMP — Composition Analysis

**Prefix:** `COMP`
**Format:** `COMP thirds=<N> <visible>/<total>_visible balance=<N> depth=<N>/<N> [edge:[<names>]]`

| Field   | Type       | Req/Opt  | Description                                    |
|---------|------------|----------|------------------------------------------------|
| thirds  | float      | required | Rule-of-thirds alignment score 0.0-1.0        |
| visible | int/int    | required | Visible objects / total objects                 |
| balance | float      | required | Visual weight balance 0.0-1.0                 |
| depth   | int/int    | required | Depth layers used / total available            |
| edge    | [names]    | optional | Objects touching the frame edge                |

**Example:**
```
COMP thirds=0.65 9/9_visible balance=0.55 depth=3/3 edge:[Floor,Ceiling]
```

**Reasoning:** Thirds score near 1.0 = good rule-of-thirds composition. Balance near 0.5 = evenly weighted frame. depth=3/3 means objects span foreground, midground, and background. Edge objects are cropped by the frame — may be intentional or a framing problem.

---

### 15. MVIEW — Multi-View Coverage

**Prefix:** `MVIEW`
**Format:** `MVIEW <view_name>: <content>`

Top view shows XY positions + floor-plane overlap. Front view shows vertical tiers (floor/mid/ceiling). Light-POV views show coverage maps.

| Field    | Type          | Req/Opt  | Description                          |
|----------|---------------|----------|--------------------------------------|
| view     | string        | required | View name (top, front, light POV)    |
| content  | varies        | required | View-specific content                |

**Examples:**
```
MVIEW top: Floor[0,0] Crate_A[1,2] Barrel[-1,3] overlap:Crate_A+Barrel
MVIEW front: floor=[Floor,Crate_A] mid=[Shelf] ceiling=[Light]
MVIEW KeyLight_POV: Crate_A=12% Floor=35%
```

**Reasoning:** Shows what is visible from alternate viewpoints. Top view reveals spatial layout that the camera might not show. Front view shows vertical distribution. Useful for verifying object placement and checking if something is hidden.

---

### 16. SPATIAL — Spatial Facts

**Prefix:** `SPATIAL`
**Format:** `SPATIAL <obj_name> <fact_type> <key>=<value> ...`

Objective measurements, not judgments. Context determines whether each fact is a problem.

| Fact Type          | Description                                            |
|--------------------|--------------------------------------------------------|
| no_light_sources   | Scene has zero illumination — render will be black     |
| surface_intersect  | Object center at surface level, half inside            |
| bbox_below_surface | Object bounding box extends below a surface            |
| bbox_extends_into  | Object penetrates another object's bounding box        |
| no_material_slots  | Object has no material assigned                        |
| inside_bbox        | Object fully inside another's bounding box             |
| no_ground_below    | No surface detected below object                       |
| near_plane         | Object near camera clipping plane                      |
| energy_zero        | Light source has zero energy output                    |
| scale_diagonal     | Object scale unusually large or small                  |
| scale_ratio        | Non-uniform scale axes                                 |
| zero_dimensions    | Object has zero-size bounding box                      |
| off_camera         | Object not visible from camera                         |
| flipped_normals    | >50% normals inverted (mesh likely inside-out)         |

**Examples:**
```
SPATIAL Crate_A surface_intersect surface=Floor depth=0.15m suggest_z=0.25
SPATIAL no_light_sources
SPATIAL Table bbox_below_surface surface=Floor pct=30%
```

---

### 17. VERIFY — Transform Verification

**Prefix:** `VERIFY`
**Format:** `VERIFY FAIL <obj_name> <reason>`

| Field  | Type   | Req/Opt  | Description                       |
|--------|--------|----------|-----------------------------------|
| result | enum   | required | Always FAIL (silent on success)   |
| object | string | required | Object that failed verification   |
| reason | string | required | What went wrong                   |

**Example:**
```
VERIFY FAIL Chair_01 parent_moved_mesh_static mesh_at=[0,0,0] parent_at=[3,2,0]
```

**Reasoning:** Post-transform mechanical verification. Only emitted on FAILURE — no output means the transform worked correctly. Catches hierarchy bugs where the parent empty moved but mesh children didn't follow.

---

### 18. ASSEMBLY — Co-located Parts

**Prefix:** `ASSEMBLY`
**Format:** `ASSEMBLY "<name>" members=[<names>] center=[x,y,z] types=<type1>+<type2>`

| Field   | Type       | Req/Opt  | Description                              |
|---------|------------|----------|------------------------------------------|
| name    | string     | required | Assembly name (quoted)                   |
| members | [names]    | required | Member object names                      |
| center  | Vec3       | required | Assembly center position                 |
| types   | string     | required | Member types joined with +               |

**Example:**
```
ASSEMBLY "Desk Lamp" members=[Lamp_Base,Lamp_Arm,Lamp_Shade,Bulb] center=[2,1,0.8] types=MESH+LIGHT
```

**Reasoning:** Identifies co-located multi-type objects forming a functional unit. When duplicating or deleting one member, handle all members together.

---

### 19. CONTAIN — Containment

**Prefix:** `CONTAIN`
**Format:** `CONTAIN <outer> contains <inner> full|partial`

| Field | Type   | Req/Opt  | Description                          |
|-------|--------|----------|--------------------------------------|
| outer | string | required | Container object name                |
| inner | string | required | Contained object name                |
| mode  | enum   | required | full (entirely inside) or partial    |

**Example:**
```
CONTAIN Room contains Sofa full
CONTAIN Bookshelf contains Book_01 partial
```

**Reasoning:** Shows which objects are inside other objects' bounding boxes. Cross-reference with OBJ `transparent` flag — a light inside a transparent container is expected, but inside an opaque one is a problem.

---

### 20. HIER — Hierarchy Chain

**Prefix:** `HIER`
**Format:** `HIER <child> > <parent> [> <grandparent> ...]`

| Field | Type       | Req/Opt  | Description                             |
|-------|------------|----------|-----------------------------------------|
| chain | name > name| required | Child-first hierarchy chain, ` > ` separated |

**Examples:**
```
HIER Crate_B > Crate_A
HIER Wheel_FL > Axle_Front > Car
```

**Reasoning:** Shows parent-child relationships. If a parent moves, all children move with it. Useful for understanding which objects are attached to or part of other objects.

---

### 21. GRP — Group/Collection

**Prefix:** `GRP`
**Format:** `GRP <group_name>: <member1>, <member2>, ...`

| Field   | Type       | Req/Opt  | Description                    |
|---------|------------|----------|--------------------------------|
| name    | string     | required | Group/collection name          |
| members | name, name | required | Comma-space-separated members  |

**Examples:**
```
GRP Storage: Crate_A, Crate_B, Barrel
GRP Structure: Floor, Ceiling, Wall_N
```

**Reasoning:** Logical grouping of objects. Tells you what objects belong together semantically. Useful for bulk operations ("select all Storage items") and understanding scene organization.

---

### 22. PHYS — Physics State

**Prefix:** `PHYS`
**Format:** `PHYS <name> <type> mass=<Nkg> [vel=<vec3>] [sleeping]`

| Field  | Type   | Req/Opt  | Description                          |
|--------|--------|----------|--------------------------------------|
| name   | string | required | Object name                          |
| type   | enum   | required | static, dynamic, kinematic           |
| mass   | Nkg    | required | Mass in kilograms                    |
| vel    | Vec3   | optional | Linear velocity                      |
| sleeping| flag  | optional | Physics body is at rest              |

**Examples:**
```
PHYS Crate_A dynamic mass=25kg sleeping
PHYS Floor static mass=0kg sleeping
```

**Reasoning:** Static = immovable (floors, walls). Dynamic = affected by physics (can fall, be pushed). Kinematic = scripted movement. "sleeping" means at rest.

---

### 23. ANIM — Animation State

**Prefix:** `ANIM`
**Format:** `ANIM <name> action=<action_name> frame=<current>/<total> <playing|stopped>`

| Field   | Type   | Req/Opt  | Description                    |
|---------|--------|----------|--------------------------------|
| name    | string | required | Object name                    |
| action  | string | required | Action/clip name               |
| frame   | int/int| required | Current frame / total frames   |
| state   | enum   | required | playing or stopped             |

**Example:**
```
ANIM Guard action=Patrol frame=45/120 playing
```

---

### 24. DELTA — Change Description

**Prefix:** `DELTA`
**Format:** `DELTA <free_text>`

**Note:** DELTA is attached separately via the auto-delta system, not as part of the main DSL output from `get_scene_perception`. It appears in `_auto_delta` on tool results, comparing the scene before and after a modifying command.

**Example:**
```
DELTA Crate_A moved [0.5,0,0] (+X)
DELTA Guard rotation changed 45° around Z
```

---

### 25. RAY — Camera Ray Grid

**Prefix:** `RAY`
**Format:** `RAY <W>x<H> <name>=<N%> ... [empty=<N%>]`

| Field      | Type            | Req/Opt  | Description                        |
|------------|-----------------|----------|------------------------------------|
| resolution | WxH             | required | Grid dimensions                    |
| coverage   | name=N% pairs   | required | Per-object ray hit percentages     |
| empty      | empty=N%        | optional | Percentage of rays hitting nothing |

**Example:**
```
RAY 12x12 Crate_A=12% Barrel=10% Floor=30% empty=5%
```

---

### 26. CONTACT — Contact Pair (Reserved)

**Note:** Reserved — not emitted by BlenderWeave. Defined in the Perspicacity spec for game engines that provide physics contact data.

**Prefix:** `CONTACT`
**Format:** `CONTACT <objA><><objB> normal=<vec3> force=<NN> surface=<name>`

---

### 27. SND — Sound Source (Reserved)

**Note:** Reserved — not emitted by BlenderWeave. Defined in the Perspicacity spec for game engines with spatial audio.

**Prefix:** `SND`
**Format:** `SND <name> type=<snd_type> vol=<N> dist=<Nm> dir=<direction> occ=<N>`

---

## Tier Model

Perspicacity organizes data into 6 tiers of increasing abstraction:

| Tier | Name     | Line Types                              | Purpose                          |
|------|----------|-----------------------------------------|----------------------------------|
| 0    | Identity | SCENE, CAM, LIGHT, OBJ, SGROUP, ASSEMBLY, FOCUS | What exists and where   |
| 1    | Spatial  | REL, VERIFY, CONTAIN, SPATIAL           | How objects relate spatially     |
| 2    | Visual   | COMP, RAY, MVIEW                        | Camera framing and coverage      |
| 3    | Physical | LIT, SHAD, MAT, HARMONY, PALETTE, WORLD, PHYS, CONTACT, SND | Lighting, materials, physics |
| 4    | Semantic | HIER, GRP                               | Logical structure                |
| 5    | Temporal | ANIM, DELTA                             | Animation and change over time   |

Note: In the text format, output order differs from tier order for readability — critical facts and per-object data come first, aggregate summaries last.

---

## Reasoning Guide

**Finding objects:** Read OBJ lines. They are sorted front-to-back by depth. The first OBJ is closest to camera. Coverage% tells you how much screen space each takes. Quadrant tells you where in the frame.

**Spatial queries:** REL lines give pairwise distance and camera-relative direction. "A→B 3m left" means B is 3m to the left of A from the camera's viewpoint. Check "contact" flag for touching objects, "above/below" for vertical stacking.

**Lighting checks:** LIT lines show incidence angle and normalized intensity per light-surface pair. Low angle + high intensity = well-lit surface. SHAD lines show where shadows fall and what casts them. Contact shadows ground objects; gaps mean floating.

**Material issues:** MAT lines describe appearance. Notes after `--` flag problems ("needs env reflections", "needs normal map"). UNREADABLE means the material is broken. Cross-reference with WORLD — metallic materials need HDRI or env maps.

**Composition:** COMP shows thirds score, balance, and depth layer usage. RAY gives precise per-object coverage percentages. MVIEW shows coverage from alternate angles (useful for verifying hidden objects).

**Hierarchy and groups:** HIER shows parent-child chains. GRP shows logical collections. SGROUP aggregates similar objects. Use together to understand scene organization.

**Physics:** PHYS shows body type and mass. CONTACT (game engine only) shows what rests on what with force values.

**Problems:** Check VERIFY lines first (transform failures), then SPATIAL facts (objective measurements). Use context to interpret — `inside_bbox` + transparent = expected, + opaque = problem.

---

## Formatting Rules

- **Vec3:** `[x,y,z]` — square brackets, comma-separated, no spaces
- **Percentages:** `N%` — no space before percent sign
- **Distances:** `Nm` — no space before m
- **Angles:** `N°` — no space before degree symbol
- **Energy:** `NW` — no space before W
- **Focal length:** `Nmm` — no space before mm
- **Mass:** `Nkg` — no space before kg
- **Force:** `NN` — no space before N
- **Luminance:** `lum=N` — float, 0.0-1.0
- **Top Z:** `top=N` — float, world-space Z coordinate
- **Source:** `src=N` — string, quoted with double quotes if contains spaces
- **Arrow:** `→` (U+2192) or `->` — both accepted, parsers must handle both
- **Names with spaces:** enclosed in double quotes (`"My Object"`)
- **Depth prefix:** `d=` on OBJ lines (e.g., `d=5.0m`)
- **Contact separator:** `<>` with no spaces (CONTACT lines)
- **Hierarchy separator:** ` > ` with spaces (HIER lines)
- **Group separator:** `, ` comma-space between members (GRP lines)
