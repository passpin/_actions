from __future__ import annotations

from decimal import Decimal

from gmdtool import GDLevel, OBJ_1

level = GDLevel("kA1,0")
level.metadata["k2"] = "gmdtool procedural example"

group = level.new.group()

# Normal Python is the scripting language. Decimal/string arithmetic avoids
# accidental binary-float spelling in exact GD numeric data.
for i in range(100):
    x = i * 30
    y = 300 + (i % 10) * 6
    block = OBJ_1(x=x, y=y, groups=[group])
    level.add(block)

group.move(x=90, duration=Decimal("0.5"), at=(300, 300))
level.validate().raise_for_errors()
level.save("procedural_example.gmd")
