<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;text=DEMO&amp;fontColor=E2E8F0&amp;fontSize=54&amp;fontAlignY=50"
    alt="DEMO banner"
  />
</p>

# Demo samples

This directory keeps the small public demo inputs plus expected `.golden` / `.stdin` companions where available.

The historical aggregate demo scripts are not present in the cleaned archive. Use the current `ouro1` wrapper for narrow checks, for example:

```sh
sh scripts/bootstrap.sh
sh scripts/ouro1.sh check samples/demo/01_hello.ouro
sh scripts/ouro1.sh run samples/demo/01_hello.ouro
sh scripts/ouro1.sh build samples/demo/02_io_echo.ouro
```

Keep demo files small and directly runnable through the current bootstrap path. New IO/effect demos should use the active `do let! x := action` spelling unless the file is intentionally testing the legacy `<-` form.

<p align="center">
  <img
    width="100%"
    src="https://capsule-render.vercel.app/api?type=waving&amp;height=220&amp;color=0:0B1220,50:1E1B4B,100:4F46E5&amp;section=footer"
    alt=""
  />
</p>
