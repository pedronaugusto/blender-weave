import bpy
import traceback

from ._utils import select_only


def manage_actions(action, object_name=None, action_name=None, source_action=None,
                   frame=None, data_path=None, interpolation=None, frame_start=None,
                   frame_end=None):
    """Manage animation actions: create, assign, list, duplicate, delete_keyframe,
    insert_keyframe_all, bake_animation, set_interpolation.

    Args:
        action: Operation —
            "create" — create a new empty action
            "assign" — assign action to object's animation data
            "list" — list all actions in file
            "duplicate" — duplicate an existing action with new name
            "delete_keyframe" — delete keyframe at frame on data_path
            "insert_keyframe_all" — keyframe all transforms at frame
            "bake_animation" — bake simulation/constraint results to keyframes
            "set_interpolation" — set FCurve interpolation type
        object_name: Name of the object
        action_name: Name of the action to create/assign/target
        source_action: Name of source action (for duplicate)
        frame: Frame number (for keyframe ops)
        data_path: Property data path (for delete_keyframe, set_interpolation)
        interpolation: Interpolation type — CONSTANT, LINEAR, BEZIER
        frame_start: Start frame for bake_animation
        frame_end: End frame for bake_animation

    Returns:
        dict with operation result
    """
    try:
        if action == "create":
            if not action_name:
                return {"error": "action_name is required for create"}
            act = bpy.data.actions.new(name=action_name)
            return {
                "success": True,
                "message": f"Created action '{act.name}'",
                "action_name": act.name,
            }

        elif action == "assign":
            if not object_name or not action_name:
                return {"error": "object_name and action_name are required for assign"}
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            act = bpy.data.actions.get(action_name)
            if not act:
                return {"error": f"Action not found: {action_name}"}
            if not obj.animation_data:
                obj.animation_data_create()
            obj.animation_data.action = act
            return {
                "success": True,
                "message": f"Assigned action '{action_name}' to '{object_name}'",
            }

        elif action == "list":
            actions = []
            for act in bpy.data.actions:
                actions.append({
                    "name": act.name,
                    "users": act.users,
                    "frame_range": [int(act.frame_range[0]), int(act.frame_range[1])],
                    "fcurve_count": len(act.fcurves),
                })
            return {
                "success": True,
                "actions": actions,
                "total": len(actions),
            }

        elif action == "duplicate":
            if not source_action or not action_name:
                return {"error": "source_action and action_name are required for duplicate"}
            src = bpy.data.actions.get(source_action)
            if not src:
                return {"error": f"Source action not found: {source_action}"}
            new_act = src.copy()
            new_act.name = action_name
            return {
                "success": True,
                "message": f"Duplicated '{source_action}' as '{new_act.name}'",
                "action_name": new_act.name,
            }

        elif action == "delete_keyframe":
            if not object_name:
                return {"error": "object_name is required for delete_keyframe"}
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            if frame is None:
                return {"error": "frame is required for delete_keyframe"}

            dp = data_path or "location"
            prop_map = {"location": "location", "rotation": "rotation_euler", "scale": "scale"}
            bl_path = prop_map.get(dp, dp)

            bpy.context.scene.frame_set(frame)
            try:
                obj.keyframe_delete(data_path=bl_path, frame=frame)
            except RuntimeError:
                return {"error": f"No keyframe found on '{object_name}'.{dp} at frame {frame}"}

            return {
                "success": True,
                "message": f"Deleted keyframe on '{object_name}'.{dp} at frame {frame}",
            }

        elif action == "insert_keyframe_all":
            if not object_name:
                return {"error": "object_name is required for insert_keyframe_all"}
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            if frame is None:
                return {"error": "frame is required for insert_keyframe_all"}

            bpy.context.scene.frame_set(frame)
            for dp in ("location", "rotation_euler", "scale"):
                obj.keyframe_insert(data_path=dp, frame=frame)

            return {
                "success": True,
                "message": f"Inserted keyframes for all transforms on '{object_name}' at frame {frame}",
                "frame": frame,
            }

        elif action == "bake_animation":
            if not object_name:
                return {"error": "object_name is required for bake_animation"}
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}

            select_only(obj)
            fs = frame_start or bpy.context.scene.frame_start
            fe = frame_end or bpy.context.scene.frame_end

            bpy.ops.nla.bake(
                frame_start=fs,
                frame_end=fe,
                only_selected=True,
                visual_keying=True,
                clear_constraints=False,
                bake_types={'OBJECT'},
            )

            return {
                "success": True,
                "message": f"Baked animation on '{object_name}' (frames {fs}-{fe})",
                "frame_range": [fs, fe],
            }

        elif action == "set_interpolation":
            if not object_name:
                return {"error": "object_name is required for set_interpolation"}
            obj = bpy.data.objects.get(object_name)
            if not obj:
                return {"error": f"Object not found: {object_name}"}
            if not interpolation:
                return {"error": "interpolation is required (CONSTANT, LINEAR, BEZIER)"}
            if not obj.animation_data or not obj.animation_data.action:
                return {"error": f"No animation data on '{object_name}'"}

            dp = data_path
            prop_map = {"location": "location", "rotation": "rotation_euler", "scale": "scale"}
            if dp:
                dp = prop_map.get(dp, dp)

            changed = 0
            for fc in obj.animation_data.action.fcurves:
                if dp and fc.data_path != dp:
                    continue
                for kp in fc.keyframe_points:
                    kp.interpolation = interpolation
                    changed += 1

            return {
                "success": True,
                "message": f"Set {interpolation} interpolation on {changed} keyframes",
                "keyframes_changed": changed,
            }

        else:
            return {"error": f"Unknown action: {action}. Use: create, assign, list, duplicate, "
                    "delete_keyframe, insert_keyframe_all, bake_animation, set_interpolation"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"Action operation failed: {str(e)}"}


def manage_nla(object_name, action, track_name=None, action_name=None,
               start_frame=1, properties=None):
    """Manage NLA tracks and strips for non-linear animation.

    Args:
        action: Operation —
            "create_track" — create NLA track on object
            "add_strip" — push action as NLA strip on track
            "list_tracks" — list all NLA tracks with strips
            "set_strip" — set strip properties (influence, extrapolation, blend_in/out)
        object_name: Name of the object
        track_name: Name of the NLA track
        action_name: Name of the action (for add_strip)
        start_frame: Start frame for the strip (default 1)
        properties: Dict of strip properties to set

    Returns:
        dict with operation result
    """
    try:
        if not object_name:
            return {"error": "object_name is required"}

        obj = bpy.data.objects.get(object_name)
        if not obj:
            return {"error": f"Object not found: {object_name}"}

        if not obj.animation_data:
            obj.animation_data_create()

        if action == "create_track":
            if not track_name:
                return {"error": "track_name is required for create_track"}
            track = obj.animation_data.nla_tracks.new()
            track.name = track_name
            return {
                "success": True,
                "message": f"Created NLA track '{track.name}' on '{object_name}'",
                "track_name": track.name,
            }

        elif action == "add_strip":
            if not track_name or not action_name:
                return {"error": "track_name and action_name are required for add_strip"}
            track = None
            for t in obj.animation_data.nla_tracks:
                if t.name == track_name:
                    track = t
                    break
            if not track:
                return {"error": f"NLA track not found: {track_name}"}
            act = bpy.data.actions.get(action_name)
            if not act:
                return {"error": f"Action not found: {action_name}"}

            strip = track.strips.new(action_name, int(start_frame), act)

            if properties:
                for key, val in properties.items():
                    if hasattr(strip, key):
                        setattr(strip, key, val)

            return {
                "success": True,
                "message": f"Added strip '{strip.name}' to track '{track_name}'",
                "strip_name": strip.name,
                "frame_start": strip.frame_start,
                "frame_end": strip.frame_end,
            }

        elif action == "list_tracks":
            tracks = []
            for track in obj.animation_data.nla_tracks:
                strips = []
                for strip in track.strips:
                    strips.append({
                        "name": strip.name,
                        "action": strip.action.name if strip.action else None,
                        "frame_start": strip.frame_start,
                        "frame_end": strip.frame_end,
                        "influence": strip.influence,
                        "blend_type": strip.blend_type,
                    })
                tracks.append({
                    "name": track.name,
                    "mute": track.mute,
                    "strips": strips,
                })
            return {
                "success": True,
                "object_name": obj.name,
                "tracks": tracks,
                "total_tracks": len(tracks),
            }

        elif action == "set_strip":
            if not track_name or not properties:
                return {"error": "track_name and properties are required for set_strip"}
            strip_name = properties.pop("strip_name", None) or action_name
            if not strip_name:
                return {"error": "strip_name (in properties) or action_name is required"}

            track = None
            for t in obj.animation_data.nla_tracks:
                if t.name == track_name:
                    track = t
                    break
            if not track:
                return {"error": f"NLA track not found: {track_name}"}

            strip = None
            for s in track.strips:
                if s.name == strip_name:
                    strip = s
                    break
            if not strip:
                return {"error": f"Strip not found: {strip_name}"}

            changed = []
            for key, val in properties.items():
                if hasattr(strip, key):
                    setattr(strip, key, val)
                    changed.append(key)

            return {
                "success": True,
                "message": f"Updated strip '{strip_name}': {', '.join(changed)}",
                "changed": changed,
            }

        else:
            return {"error": f"Unknown action: {action}. Use: create_track, add_strip, list_tracks, set_strip"}
    except Exception as e:
        traceback.print_exc()
        return {"error": f"NLA operation failed: {str(e)}"}
