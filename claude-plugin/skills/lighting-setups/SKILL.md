---
name: lighting-setups
description: Professional lighting setups for BlenderWeave — three-point, studio, product, architectural, and dramatic lighting recipes with manage_lights parameters.
---

# Lighting Setups

Proven lighting configurations using `manage_lights`. All setups assume a scene centered at origin with camera 3-5m away.

## Three-Point Lighting (Standard)

The foundation. Key light provides main illumination, fill softens shadows, rim separates subject from background.

### Key Light (main, strong, slightly warm)
```
manage_lights(action="create", light_name="Key", light_type="AREA",
    location=[3, -2, 3], energy=500, color=[1.0, 0.95, 0.9],
    size=1.0)
```
Point at subject: `manage_constraints(action="add", object_name="Key", type="TRACK_TO", target="Subject")`

### Fill Light (softer, cooler, opposite side)
```
manage_lights(action="create", light_name="Fill", light_type="AREA",
    location=[-2, -2, 2], energy=150, color=[0.9, 0.95, 1.0],
    size=2.0)
```

### Rim/Back Light (behind subject, separation)
```
manage_lights(action="create", light_name="Rim", light_type="POINT",
    location=[0, 3, 3], energy=300, color=[1.0, 1.0, 1.0])
```

**Check:** LIT lines should show Key→Subject with high intensity (i>0.7), Fill→Subject with medium (i≈0.3-0.5). SHAD lines should show shadows from Key only.

## Studio Product Photography

Clean, even lighting for product shots. Two large area lights, white background.

### Setup
```
# Large soft key
manage_lights(action="create", light_name="SoftKey", light_type="AREA",
    location=[2, -1, 3], energy=400, color=[1.0, 1.0, 1.0],
    size=3.0, shape="RECTANGLE", size_y=2.0)

# Fill from opposite side
manage_lights(action="create", light_name="SoftFill", light_type="AREA",
    location=[-2, -1, 2], energy=250, color=[1.0, 1.0, 1.0],
    size=2.5)

# White backdrop
manage_world(action="set_color", color=[1.0, 1.0, 1.0], strength=0.5)
```

**Goal:** Minimal shadows, even coverage. SHAD coverage should be <20% on the product surface.

## Architectural / Interior

Warm ambient with accent lighting. Uses HDRI or warm background + point lights for practicals.

### Setup
```
# Environment
manage_world(action="set_hdri", filepath="path/to/interior.hdr", strength=0.8)

# Overhead practical
manage_lights(action="create", light_name="Ceiling", light_type="POINT",
    location=[0, 0, 2.8], energy=200, color=[1.0, 0.85, 0.65])

# Window light (strong, cool daylight)
manage_lights(action="create", light_name="Window", light_type="AREA",
    location=[-3, 0, 1.5], energy=800, color=[0.85, 0.92, 1.0],
    size=2.0, shape="RECTANGLE", size_y=3.0)
```

**Check:** LIT lines should show Window dominating one side with warm Ceiling fill. SHAD from Window should create directional shadows.

## Dramatic / Cinematic

High contrast, single strong source, deep shadows.

### Setup
```
# Single hard key
manage_lights(action="create", light_name="Spot", light_type="SPOT",
    location=[2, -3, 3], energy=1000, color=[1.0, 0.9, 0.8],
    spot_size=35, spot_blend=0.3)

# Very faint ambient
manage_world(action="set_color", color=[0.02, 0.02, 0.04], strength=0.1)
```

**Goal:** SHAD coverage >50% on surfaces. Strong directional shadows. LIT lines should show high intensity on lit surfaces, near-zero on shadow side.

## Outdoor Daylight

Sun + sky HDRI.

### Setup
```
# Sun light
manage_lights(action="create", light_name="Sun", light_type="SUN",
    location=[0, 0, 10], energy=5, color=[1.0, 0.98, 0.95])
# Rotate to desired angle
transform_object(object_name="Sun", rotation=[45, 0, 30])

# Sky HDRI
manage_world(action="set_hdri", filepath="path/to/sky.hdr", strength=1.0)
```

Or use Poly Haven sky: `download_polyhaven_asset(asset_id="kloofendal_48d_partly_cloudy", asset_type="hdris")`

## Night / Low Light

Dark ambient, warm practicals, cool moonlight.

### Setup
```
# Moon (distant, cool, faint)
manage_lights(action="create", light_name="Moon", light_type="SUN",
    location=[0, 0, 10], energy=0.5, color=[0.7, 0.8, 1.0])
transform_object(object_name="Moon", rotation=[60, 0, -20])

# Street lamp (warm pool of light)
manage_lights(action="create", light_name="StreetLamp", light_type="SPOT",
    location=[3, 0, 4], energy=200, color=[1.0, 0.8, 0.5],
    spot_size=60, spot_blend=0.5)

# Dark world
manage_world(action="set_color", color=[0.005, 0.005, 0.01], strength=0.05)
```

## Diagnostic Checks

After setting up any lighting, verify with perception:

| What to Check | Where to Look | Good Sign |
|---|---|---|
| Main subject lit | LIT Key→Subject | i > 0.6 |
| Fill working | LIT Fill→Subject | i ≈ 0.2-0.4 |
| Shadows reasonable | SHAD lines | Coverage 10-60% |
| No unlit objects | LIT lines for each obj | Every object has at least one LIT entry |
| No lighting issues | SPATIAL lines | No "no_light_sources" facts |

## Common Fixes

- **"metallic_no_hdri" issue:** Add HDRI with `manage_world(action="set_hdri")`
- **Shadows too harsh:** Increase area light size or add fill light
- **Scene too dark:** Increase energy values or add ambient via world strength
- **Flat lighting:** Reduce fill intensity, increase key-to-fill ratio (3:1 is standard)
- **Color cast:** Check light colors — mix warm and cool intentionally
