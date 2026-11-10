#!/usr/bin/env python3
"""Download every font the designer offers into cad/fonts (used when building the Docker image)."""
from make_stl import FONT_FILES, font_file

for family in FONT_FILES:
    print(family, "->", font_file(family).name)
