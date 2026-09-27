#!/usr/bin/env python3
"""CD Injector 3DS. No arguments opens the app; `cd_injector.py build ...` uses the command line."""

import sys

if __name__ == "__main__":
    if len(sys.argv) > 1:
        from cdinjector.cli import main
        sys.exit(main())
    from cdinjector.gui import main
    main()
