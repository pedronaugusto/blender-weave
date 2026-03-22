---
name: material-recipes
description: PBR material recipes for BlenderWeave — ready-to-use parameter sets for common materials like wood, metal, glass, concrete, fabric, and more.
---

# Material Recipes

Ready-to-use `manage_materials` parameter sets. All values are for Principled BSDF.

## Metals

### Polished Steel
```
manage_materials(action="create", name="Steel",
    base_color=[0.55, 0.55, 0.56], metallic=1.0, roughness=0.15)
```

### Brushed Aluminum
```
manage_materials(action="create", name="Aluminum",
    base_color=[0.9, 0.9, 0.92], metallic=1.0, roughness=0.35)
```

### Gold
```
manage_materials(action="create", name="Gold",
    base_color=[1.0, 0.78, 0.34], metallic=1.0, roughness=0.2)
```

### Copper
```
manage_materials(action="create", name="Copper",
    base_color=[0.95, 0.64, 0.54], metallic=1.0, roughness=0.25)
```

### Rusted Iron
```
manage_materials(action="create", name="RustedIron",
    base_color=[0.44, 0.25, 0.15], metallic=0.6, roughness=0.85)
```

**Note:** Metallic materials need HDRI or bright environment for reflections. Check MAT lines — if they say "needs env reflections", add an HDRI with `manage_world(action="set_hdri")`.

## Glass & Transparents

### Clear Glass
```
manage_materials(action="create", name="Glass",
    base_color=[1.0, 1.0, 1.0], roughness=0.0, transmission=1.0, ior=1.45)
```

### Frosted Glass
```
manage_materials(action="create", name="FrostedGlass",
    base_color=[0.95, 0.95, 0.97], roughness=0.4, transmission=1.0, ior=1.45)
```

### Colored Glass (green bottle)
```
manage_materials(action="create", name="GreenGlass",
    base_color=[0.1, 0.4, 0.15], roughness=0.05, transmission=1.0, ior=1.52)
```

### Water
```
manage_materials(action="create", name="Water",
    base_color=[0.8, 0.9, 1.0], roughness=0.0, transmission=1.0, ior=1.33)
```

**Note:** Glass/transparent materials need objects behind them to look correct. The MAT line will show "needs objects behind" as a reminder. Place objects behind glass, or add a background.

## Wood

### Light Wood (pine/birch)
```
manage_materials(action="create", name="LightWood",
    base_color=[0.76, 0.6, 0.42], metallic=0.0, roughness=0.5)
```

### Dark Wood (walnut)
```
manage_materials(action="create", name="DarkWood",
    base_color=[0.25, 0.15, 0.08], metallic=0.0, roughness=0.45)
```

### Varnished Wood
```
manage_materials(action="create", name="VarnishedWood",
    base_color=[0.4, 0.22, 0.1], metallic=0.0, roughness=0.2, coat_weight=0.7)
```

For realistic wood grain, use Poly Haven textures: `download_polyhaven_asset(asset_id="wood_cabinet_worn_long", asset_type="textures")` then `set_texture`.

## Stone & Concrete

### Concrete
```
manage_materials(action="create", name="Concrete",
    base_color=[0.5, 0.48, 0.45], metallic=0.0, roughness=0.85)
```

### Marble (white)
```
manage_materials(action="create", name="Marble",
    base_color=[0.92, 0.9, 0.88], metallic=0.0, roughness=0.15)
```

### Brick
```
manage_materials(action="create", name="Brick",
    base_color=[0.55, 0.25, 0.18], metallic=0.0, roughness=0.75)
```

For textured stone/concrete, use Poly Haven: `search_polyhaven_assets(asset_type="textures", categories="concrete")`.

## Fabric & Organic

### Cotton/Linen
```
manage_materials(action="create", name="Cotton",
    base_color=[0.85, 0.82, 0.78], metallic=0.0, roughness=0.9)
```

### Leather
```
manage_materials(action="create", name="Leather",
    base_color=[0.35, 0.2, 0.1], metallic=0.0, roughness=0.6)
```

### Skin (stylized)
```
manage_materials(action="create", name="Skin",
    base_color=[0.8, 0.6, 0.5], metallic=0.0, roughness=0.5,
    subsurface_weight=0.3)
```

## Plastic & Rubber

### Glossy Plastic
```
manage_materials(action="create", name="GlossyPlastic",
    base_color=[0.8, 0.1, 0.1], metallic=0.0, roughness=0.15)
```

### Matte Plastic
```
manage_materials(action="create", name="MattePlastic",
    base_color=[0.3, 0.3, 0.35], metallic=0.0, roughness=0.6)
```

### Rubber
```
manage_materials(action="create", name="Rubber",
    base_color=[0.15, 0.15, 0.15], metallic=0.0, roughness=0.95)
```

## Emissive

### Neon Glow
```
manage_materials(action="create", name="Neon",
    base_color=[0, 0, 0], metallic=0.0, roughness=0.5,
    emission_color=[0.2, 0.8, 1.0], emission_strength=10.0)
```

### Warm Light Bulb
```
manage_materials(action="create", name="WarmGlow",
    base_color=[0, 0, 0], metallic=0.0, roughness=0.5,
    emission_color=[1.0, 0.85, 0.6], emission_strength=5.0)
```

## Color Ramp Patterns

For gradient materials, use `manage_materials(action="edit_color_ramp")`:

```
manage_materials(action="edit_color_ramp", material_name="Gradient",
    node_name="Color Ramp",
    stops=[
        {"position": 0.0, "color": [0.1, 0.05, 0.02]},
        {"position": 0.5, "color": [0.4, 0.2, 0.1]},
        {"position": 1.0, "color": [0.8, 0.6, 0.4]}
    ])
```

## Tips

- Always check MAT lines after assigning materials — they flag issues
- Use `render_region(object_name="...", resolution=512)` to preview materials quickly
- Metallic + no HDRI = dull. Add environment lighting first.
- Glass + nothing behind = MAT shows "needs objects behind". Place background objects.
- For PBR textures from Poly Haven, use `set_texture` instead of manual material creation
