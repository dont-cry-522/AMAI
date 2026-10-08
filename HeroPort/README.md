# Forsaken Paladin: personal classic compatibility experiment

This opt-in map port targets Warcraft III TFT 1.24e. It does not change the game
installation or the default AMAI roster. The player can recruit the new neutral
hero after 135 seconds. Both ordinary and voice-enabled maps retain the existing
v0.5 DeepSeek bridge unchanged. AMAI does **not** yet recruit this custom hero.

The private build uses Blizzard's public retail **3.0.0.24268** SD resources and
ability data, obtained from its patch/CDN manifests. PTR values are not mixed in.
Blizzard assets, private configuration and generated maps are not committed here.

- `forsaken.j`: old-engine spells, Tavern stock and official voice callbacks.
- `build_test_maps.py`: makes a new map from an existing v0.5 map and prepared
  private assets, preserving terrain, placed units and all original AI/bridge
  scripts. Refuses existing outputs and inputs with custom object tables.
- `validate_imports.py`: validates the actual extracted models, textures, sounds,
  custom object data and resource references. Run both bundled JASS parsers too.
- `add_to_maps.py`: scans existing maps for Tavern creation, merges the prepared
  hero objects/imports without discarding map-specific records, and writes new
  maps into a separate directory. Original map names and AI modes are preserved.
  Both JASS parsers and byte comparisons run for every output. ID/resource
  conflicts are rejected. Source maps and the prepared resource template are
  read-only. Work/extracted files stay outside the delivery directory.
- `python -m unittest discover -s HeroPort -p test_add_to_maps.py` checks object
  preservation, collision rejection and script initialization order.

## Compatibility limits — not an exact official implementation

- SD model format 1800 is converted to 800. Four weighted influences are
  approximated with classic equal-weight matrix groups. Bone/animation tracks
  remain intact; maximum individual weight quantization error is 0.18334.
  New-format portrait lights, bind-pose metadata and Popcorn emitters are omitted.
  The original mesh-based classic team glow is retained.
- DDS becomes RGBA TGA (maximum 512; aura textures 256). Official English OGG
  speech/effects become mono 22,050 Hz 16-bit PCM WAV. No AI voice replacement.
- Dash advances at 1,000 units/sec up to 725 units, checking old terrain and
  collision placement. Pathing/cancellation can differ from the new native spell.
- Consecration follows retail healing/damage values but excludes air/mechanical
  units at all levels, matching the subsequently announced targeting correction.
- Universal healing adjustments sample **net positive health change every 0.1s**.
  This also affects natural regeneration and cannot perfectly detect simultaneous
  damage/healing or overhealing at maximum health. The port's own heals are
  adjusted directly. This is an approximation, not a true heal-event hook.
- Magic resistance uses the classic item-resistance ability; item interactions
  need game testing. Aura refresh is 0.5s. Multiple friendly auras use the highest
  level. Cleansing uses the old engine's ordinary magical-buff removal flags;
  dispel edge cases can differ. Damage bonus counts at most 19 removed debuffs.
- Chinese hero/skill text and original English voice callbacks are supplied.
  Selection/movement/attack acknowledgements use map triggers so no global sound
  tables or other heroes' sound resources are overwritten.

Static parsing, MPQ round-trip verification and browser model inspection do not
establish game compatibility. **No Warcraft process was started on the company
computer. Real 1.24e gameplay and spell behavior remain unverified.**

## Home test

Merge only the add-on's `maps/AMAI_DeepSeek` and `maps/AMAI_DeepSeek_Voice` new map
files into the matching folders of the existing complete `AMAI_OneClick_v05`
package. Its existing launcher installs all `.w3x` files in these two folders.
Keep the original package, maps, credentials and single bridge window.

First verify Tavern recruitment after 2:15, four learnable spells, portrait,
animation, team color, attack/selection voice, death and altar revival. Then test
ground collision, allied living healing versus enemy Undead damage, magic
resistance, dispels, ultimate buffs and cooldowns. Record failures and preserve
original maps; do not replace the game or patch its DLLs.
