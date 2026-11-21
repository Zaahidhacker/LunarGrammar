"""The reference mark, palette, and vector-style motion for the Luna capsule."""

import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).with_name("assets")
FONT_DIR = ASSETS / "fonts"
LIME = "#BFF549"
GREEN_INK = "#365716"
WORK_WIDTH = 226
HEIGHT = 54


@lru_cache(maxsize=24)
def font(size: int, weight="Regular"):
    return ImageFont.truetype(str(FONT_DIR / f"Poppins-{weight}.ttf"), size)


def logo(draw, x, y, scale, color=LIME):
    """Trace the supplied 22 px chat mark, including its stepped tail."""
    def shape(points):
        draw.polygon([(round(x + px * scale), round(y + py * scale)) for px, py in points], fill=color)

    shape([(5, 0), (18, 0), (18, 3.6), (5.2, 3.6), (3.6, 5), (3.6, 12.6),
           (5.2, 15), (14.5, 15), (14.5, 18), (7, 18), (7, 22),
           (3.7, 18.2), (1.3, 16), (0, 13), (0, 5), (1.3, 2.3)])
    shape([(7.3, 7.8), (18, 7.8), (18, 11.1), (7.3, 11.1)])
    shape([(18.9, 11.2), (22, 11.2), (22, 19), (18.9, 19)])


def tray_image():
    image = Image.new("RGBA", (128, 128))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((4, 4, 123, 123), 30, fill="#111313", outline="#343833", width=3)
    logo(draw, 23, 23, 3.7)
    return image


def ease(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


@dataclass(frozen=True)
class Frame:
    state: str
    label: str
    width: float
    height: float
    opacity: float
    offset: float
    wave_time: float
    transition: float


@dataclass
class Motion:
    state: str = "hidden"
    label: str = ""
    started: float = 0.0
    finished: float = 0.0
    dismissed: bool = False

    def begin(self, now, label="Refining…"):
        self.state, self.label, self.started = "working", label, now
        self.dismissed = False

    def finish(self, state, label, now):
        if not self.dismissed:
            if self.state != "working":
                self.started = now
            self.state, self.label, self.finished = state, label, now

    def dismiss(self):
        self.state, self.dismissed = "hidden", True

    def sample(self, now, reduced=False):
        if self.state == "hidden":
            return None
        age = max(0.0, now - self.started)
        enter = 1 if reduced else ease(age / 0.16)
        width, transition, leave = WORK_WIDTH, 0.0, 0.0
        if self.state != "working":
            hold = 2.25 if self.state == "error" else 1.10
            elapsed = now - self.finished
            if elapsed >= hold + (0.0 if reduced else 0.20):
                self.state = "hidden"
                return None
            transition = 1 if reduced else ease(elapsed / 0.19)
            result_width = max(174, font(13, "Medium").getlength(self.label) + 122)
            width += (result_width - width) * transition
            leave = 0 if reduced else ease((elapsed - hold) / 0.20)
        scale = (0.96 + enter * 0.04) * (1 - leave * 0.08)
        return Frame(self.state, self.label, width * scale, HEIGHT * scale,
                     enter * (1 - leave), 5 * (1 - enter) + 6 * leave,
                     0.42 if reduced else age, transition)


def waveform_heights(t):
    return tuple(
        5 + 13 * (0.72 * (0.5 + 0.5 * math.sin(6.2 * t - i * 0.82))
                  + 0.28 * (0.5 + 0.5 * math.sin(9.7 * t + i * 0.49)))
        for i in range(9)
    )


def pill_position(work_area, width, height, dpi, offset=0.0):
    left, top, right, bottom = work_area
    x = left + max(0, (right - left - width) // 2)
    y = max(top, bottom - height - round((18 - offset) * dpi / 96))
    return x, y


def render(frame: Frame, dpi: int, appearance: str) -> Image.Image:
    width, height = round(frame.width * dpi / 96), round(frame.height * dpi / 96)
    ss = 2
    s = height * ss / HEIGHT
    w, h = width * ss, height * ss
    im = Image.new("RGBA", (w, h))
    draw = ImageDraw.Draw(im)
    center = h / 2 - s
    dark = appearance == "dark"
    surface, border = ("#0F1010", "#313431") if dark else ("#F5F7F1", "#D3D8CA")
    ink, muted = ("#E7EAE4", "#9DA49A") if dark else ("#222923", "#535C50")
    accent = LIME if dark else GREEN_INK
    amber = "#E6B779" if dark else "#885010"

    for inset, alpha in [(1, 16), (2, 26), (3, 43), (4, 60)]:
        draw.rounded_rectangle((inset*s, (5+inset/2)*s, w-inset*s, h-inset*s),
                               radius=26*s, fill=(0, 0, 0, alpha))
    draw.rounded_rectangle((5*s, 4*s, w-5*s, h-6*s), radius=22*s, fill=surface,
                           outline=border, width=max(1, round(s)))
    logo(draw, 19*s, center-10*s, 0.94*s, accent)
    draw.line((49*s, center-11*s, 49*s, center+11*s), fill=border, width=max(1, round(s)))

    blend = frame.transition
    if blend < 1:
        wave = Image.new("RGBA", im.size)
        marks = ImageDraw.Draw(wave)
        rgb = tuple(int(accent[i:i+2], 16) for i in (1, 3, 5))
        for i, bar in enumerate(waveform_heights(frame.wave_time)):
            x = (58 + i * 6.6) * s
            half = bar * s * (1 - 0.7 * blend) / 2
            marks.rounded_rectangle((x, center-half, x+2.8*s, center+half), radius=1.4*s,
                                    fill=(*rgb, round(255 * (1 - blend))))
        wave_alpha = round(255 * (1 - blend))
        working_label = frame.label if frame.state == "working" else "Refining…"
        label_size = 12
        while label_size > 8 and font(round(label_size*s)).getlength(working_label) > 68*s:
            label_size -= 1
        marks.text((124*s, center), working_label, font=font(max(8, round(label_size*s))),
                   fill=(*tuple(int(muted[i:i+2], 16) for i in (1, 3, 5)), wave_alpha), anchor="lm")
        im = Image.alpha_composite(im, wave)
        draw = ImageDraw.Draw(im)
    if blend:
        result = Image.new("RGBA", im.size)
        marks = ImageDraw.Draw(result)
        x = 66*s
        mark = accent if frame.state in ("success", "unchanged") else amber
        stroke = max(1, round(2*s))
        if frame.state == "success":
            marks.line((x-6*s, center, x-1*s, center+5*s, x+7*s, center-5*s),
                       fill=mark, width=stroke, joint="curve")
        elif frame.state == "unchanged":
            marks.ellipse((x-4*s, center-4*s, x+4*s, center+4*s), outline=mark, width=stroke)
        else:
            marks.line((x, center-6*s, x, center+s), fill=mark, width=stroke)
            marks.ellipse((x-s, center+4*s, x+s, center+6*s), fill=mark)
        marks.text((82*s, center), frame.label, font=font(max(8, round(13*s)), "Medium"),
                   fill=ink, anchor="lm")
        result.putalpha(result.getchannel("A").point(lambda value: round(value * blend)))
        im = Image.alpha_composite(im, result)
        draw = ImageDraw.Draw(im)

    x = w-23*s
    for direction in (-1, 1):
        draw.line((x-3.7*s, center-direction*3.7*s, x+3.7*s, center+direction*3.7*s),
                  fill=muted, width=max(1, round(1.1*s)))
    return im.resize((width, height), Image.Resampling.LANCZOS)
