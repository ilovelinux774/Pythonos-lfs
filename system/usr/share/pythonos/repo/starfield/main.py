"""starfield — because every OS deserves one."""

import random
import shutil
import sys
import time

STARS = "*+.:."


def frame(width, height, stars):
    grid = [[" "] * width for _ in range(height)]
    for x, y, ch in stars:
        if 0 <= x < width and 0 <= y < height:
            grid[y][x] = ch
    return "\n".join("".join(row) for row in grid)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    seconds = 4.0
    for arg in argv:
        if arg.startswith("--seconds="):
            try:
                seconds = float(arg.split("=", 1)[1])
            except ValueError:
                pass

    cols, rows = shutil.get_terminal_size((60, 20))
    width, height = min(cols, 70), max(min(rows - 2, 18), 6)
    random.seed()
    stars = []
    for _ in range(max(width * height // 14, 12)):
        stars.append([random.randrange(width), random.randrange(height),
                      random.choice(STARS)])

    interactive = sys.stdout.isatty()
    if interactive:
        sys.stdout.write("\x1b[?25l")
    deadline = time.time() + seconds
    try:
        tick = 0
        while time.time() < deadline:
            tick += 1
            for star in stars:
                star[0] = (star[0] + (1 if tick % 3 else 2)) % width
                if random.random() < 0.06:
                    star[1] = (star[1] + random.choice((-1, 1))) % height
                if random.random() < 0.02:
                    star[2] = random.choice(STARS)
            if interactive:
                sys.stdout.write("\x1b[H" + frame(width, height, stars))
                sys.stdout.flush()
            else:
                print(frame(width, height, stars))
                print("-" * width)
            time.sleep(0.12)
    except KeyboardInterrupt:
        pass
    finally:
        if interactive:
            sys.stdout.write("\x1b[?25h\n")
    print(f"{tick} frames of stars. PythonOS says goodnight.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
