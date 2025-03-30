#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -e

# Use ImageMagick convert to create the GIF

echo "Generating GIF using ImageMagick convert..."

# -delay: Time between frames in ticks (1/100ths of a second). 67 ticks = 0.67s (~1.5 fps).
# -loop 0: Loop infinitely.
# List all input PNGs in the desired order.
# -resize '800x>': Resize width to 800px max, maintain aspect ratio ONLY if wider. Remove if no resize needed.
# -layers Optimize: Optimize GIF layers (optional, can reduce size).
convert -delay 67 -loop 0 \
    demo_output_multistep/step_0_state.png \
    demo_output_multistep/step_0_highlight.png \
    demo_output_multistep/step_1_state.png \
    demo_output_multistep/step_1_highlight.png \
    demo_output_multistep/step_2_state.png \
    demo_output_multistep/step_2_highlight.png \
    demo_output_multistep/final_state.png \
    -resize '800x>' \
    -layers Optimize \
    omnimcp_demo.gif

echo "Generated omnimcp_demo.gif"

# --- How to Adjust GIF Speed ---
# - Change the value after `-delay`. Lower number = faster animation.
#   - e.g., `-delay 50` (0.5s / 2 fps), `-delay 33` (~0.33s / 3 fps)
