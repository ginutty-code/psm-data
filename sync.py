"""
Explicit sync step: copies the compiled Output/*.lua files into the psm-addon
repo. Generators only write to Output/; this is the one thing that crosses
the repo boundary, and it runs by hand now rather than as a side effect of
every generator run (ARCHITECTURE_PLAN.md, A1).
"""

from config import sync_output_to_addon


def main():
    sync_output_to_addon()


if __name__ == "__main__":
    main()
