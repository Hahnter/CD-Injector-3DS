# Third-party notices

CD Injector 3DS bundles or builds on the following software. It includes **no**
games or BIOS files.

**This project's own code** (the Python app in `cdinjector/`, the scripts and the tests) is released under the MIT
License (see `LICENSE`). Everything below is other people's work and keeps its own license. Because PicoDrive is
included in every CIA, the complete download is free and non-commercial regardless of the MIT license on our code.

**Banner artwork.** The frame, the title plate and the banner sound are drawn or
synthesised by the program. They contain no Nintendo, Sega, NEC or NSUI artwork.
The words "Virtual Console" on the title plate only describe the style; this
project is not affiliated with or endorsed by Nintendo, Sega or NEC.

**Fonts.** No font is bundled. The title plate uses Arial Bold (or the nearest match) from your system, or a font file you choose. Sony's SCE-PS3 Rodin fonts are proprietary and are not included.

**NSUI files.** If you choose a banner and icon exported from NSUI (New Super Ultimate Injector for 3DS), the app only reads the files you give it. It contains no NSUI code or assets, and a banner made this way carries NSUI's 3D model, so don't share the CIAs you make.

## Emulators inside every CIA

### emus3ds (TemperPCE for 3DS, PicoDrive for 3DS front end)
- Original: bubble2k16, <https://github.com/bubble2k16/emus3ds>
- Continued by R-YaTian: <https://github.com/R-YaTian/emus3ds>, the version built
  here (commit `a10138fc13c2c90e2a520f5717be002d932d87c0`)
- Modified by this project with `patches/autoboot-forwarder.patch`: auto-boot,
  RomFS game and BIOS, save redirection, and forwarder fixes.
- Neither repository contains a license file, and the question is still open
  upstream (<https://github.com/bubble2k16/emus3ds/issues/32>). It is
  redistributed here, as it is widely redistributed elsewhere, with full credit
  and full source available. If you are an author and want it removed or
  credited differently, open an issue and it will be done.

### TemperPCE
PC Engine / TurboGrafx-16 emulator by Exophase (Temper), ported to 3DS by
bubble2k16. No license text is included in the emus3ds sources.

### PicoDrive
Copyright (c) Dave 2004, notaz 2006–2013, irixxxx and contributors.
<https://github.com/notaz/picodrive> · <https://github.com/irixxxx/picodrive>

PicoDrive is distributed under the MAME-style license below. In line with it,
CD Injector 3DS is free and non-commercial, and **the complete source code of
the modified emulators is published with every release** (the pinned emus3ds
commit plus `patches/autoboot-forwarder.patch`, and a source archive attached
to each release).

```
 Redistribution and use of this code or any derivative works are permitted
 provided that the following conditions are met:

 * Redistributions may not be sold, nor may they be used in a commercial
 product or activity.

 * Redistributions that are modified from the original source must include the
 complete source code, including the source code for all components used by a
 binary built from the modified sources. However, as a special exception, the
 source code distributed need not include anything that is normally distributed
 (in either source or binary form) with the major components (compiler, kernel,
 and so on) of the operating system on which the executable runs, unless that
 component itself accompanies the executable.

 * Redistributions must reproduce the above copyright notice, this list of
 conditions and the following disclaimer in the documentation and/or other
 materials provided with the distribution.

 THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
 AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
 IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
 ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
 LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
 CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
 SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
 INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
 CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
 ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
 POSSIBILITY OF SUCH DAMAGE.
```

## Build tools bundled with the app

### bannertool
Copyright (C) 2015-2017 Steveice10. Built from <https://github.com/diasurgical/bannertool>.

```
Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
```

### makerom
CTR MAKEROM v0.18.4, the official release from <https://github.com/3DSGuy/Project_CTR>
(`makerom-v0.18.4-win_x86_64.zip`, SHA-256
`d743507dc66d4c6f8efcce05ff8f5f47163a60e54e0e0c57fa12ec2f54acdf2f`), unmodified.

```
MIT License

Copyright (c) 2014 3DSGuy
Copyright (c) 2014 applestash
Copyright (c) 2015-2022 Jakcron

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### Python runtime and libraries (packaged by PyInstaller)
The Windows app contains Python (PSF License, which also covers the libraries in Python's Windows build such as
OpenSSL, libffi and bzip2), Tcl and Tk (BSD-style licenses) and Pillow (MIT-CMU license, which also covers the image
libraries built into Pillow). Their full license texts are in the `licenses` folder next to the app.
