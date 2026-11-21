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


def bolt(draw, x, y, scale, color):
    """Draw a small vector lightning bolt (11x16 box) — no emoji glyph, so
    it renders identically on every machine (Poppins has no ⚡ glyph)."""
    draw.polygon([(round(x + px * scale), round(y + py * scale)) for px, py in
                  [(7, 0), (11, 0), (8, 7), (11, 7), (4, 16), (6, 9), (3, 9)]],
                 fill=color)


def ellipsize(text: str, font_obj, max_width: float) -> str:
    """Shorten text with … so it fits max_width in the given font."""
    if not text or font_obj.getlength(text) <= max_width:
        return text
    while text and font_obj.getlength(text + "…") > max_width:
        text = text[:-1]
    return (text + "…") if text else "…"


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
    mode_badge: str = ""
    diff_badge: str = ""
    cached: bool = False
    subtext: str = ""
    review: bool = False


@dataclass
class Motion:
    state: str = "hidden"
    label: str = ""
    started: float = 0.0
    finished: float = 0.0
    dismissed: bool = False
    mode_badge: str = ""
    diff_badge: str = ""
    cached: bool = False
    subtext: str = ""

    def begin(self, now, label="Refining…", mode_badge=""):
        self.state, self.label, self.started = "working", label, now
        self.mode_badge = mode_badge
        self.diff_badge = ""
        self.cached = False
        self.subtext = ""
        self.dismissed = False

    def finish(self, state, label, now, diff_badge="", cached=False, mode_badge=None, subtext=""):
        if not self.dismissed:
            if self.state != "working":
                self.started = now
            self.state, self.label, self.finished = state, label, now
            self.diff_badge = diff_badge
            self.cached = cached
            if mode_badge is not None:
                self.mode_badge = mode_badge
            self.subtext = subtext

    def dismiss(self):
        self.state, self.dismissed = "hidden", True

    def sample(self, now, reduced=False):
        if self.state == "hidden":
            return None
        age = max(0.0, now - self.started)
        enter = 1 if reduced else ease(age / 0.16)
        display_label = self.label

        # Base width calculation
        working_width = WORK_WIDTH
        if self.mode_badge:
            working_width = max(WORK_WIDTH, WORK_WIDTH + font(10, "Medium").getlength(self.mode_badge) + 24)

        width = working_width
        transition, leave = 0.0, 0.0
        if self.state != "working":
            # Review stays up for the worker's 30s decision window, then
            # falls through to apply — the pill must not vanish first.
            hold = 30.0 if self.state == "review" else (2.25 if self.state == "error" else 1.10)
            elapsed = now - self.finished
            if elapsed >= hold + (0.0 if reduced else 0.20):
                self.state = "hidden"
                return None
            transition = 1 if reduced else ease(elapsed / 0.19)

            extra_w = 0.0
            if self.diff_badge:
                extra_w += font(10, "Medium").getlength(self.diff_badge) + 22
            if self.cached and "cached" not in (self.diff_badge or "").lower():
                extra_w += font(9.5, "Medium").getlength("Cached") + 30
            if self.mode_badge and not self.diff_badge:
                extra_w += font(10, "Medium").getlength(self.mode_badge) + 20
            if self.subtext:
                extra_w += font(10, "Regular").getlength(self.subtext) + 16
            if self.state == "review":
                # Room for the [Discard] [Apply] buttons before the close zone.
                extra_w += 160

            # Clamp the capsule so long error/validation messages cannot push
            # the close button off the pill; the label is ellipsized to fit.
            # Review pills get a wider cap: the corrected-text preview is the
            # point, and the Apply/Discard buttons already reserve 160px.
            max_width = 560 if self.state == "review" else 420
            result_width = min(max_width, max(174, font(13, "Medium").getlength(self.label) + 122 + extra_w))
            label_font = font(13, "Medium")
            display_label = ellipsize(self.label, label_font, result_width - 122 - extra_w)
            width += (result_width - width) * transition
            leave = 0 if reduced else ease((elapsed - hold) / 0.20)

        scale = (0.96 + enter * 0.04) * (1 - leave * 0.08)
        return Frame(
            self.state, display_label, width * scale, HEIGHT * scale,
            enter * (1 - leave), 5 * (1 - enter) + 6 * leave,
            0.42 if reduced else age, transition,
            mode_badge=self.mode_badge, diff_badge=self.diff_badge,
            cached=self.cached, subtext=self.subtext,
            review=self.state == "review",
        )


def waveform_heights(t):
    return tuple(
        5 + 13 * (0.72 * (0.5 + 0.5 * math.sin(6.2 * t - i * 0.82))
                  + 0.28 * (0.5 + 0.5 * math.sin(9.7 * t + i * 0.49)))
        for i in range(9)
    )


def pill_position(work_area, width, height, dpi, offset=0.0, caret=None):
    left, top, right, bottom = work_area
    if caret is not None:
        cx, cy = caret
        margin = round(12 * dpi / 96)
        x = cx - width // 2
        y = cy + round((14 + offset) * dpi / 96)
        if y + height > bottom - margin:
            y = cy - height - round((14 - offset) * dpi / 96)
        x = max(left + margin, min(right - width - margin, x))
        y = max(top + margin, min(bottom - height - margin, y))
        return x, y

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
    coral = "#FF6B6B" if dark else "#D93838"
    ice_blue = "#60A5FA" if dark else "#1D4ED8"

    for inset, alpha in [(1, 16), (2, 26), (3, 43), (4, 60)]:
        draw.rounded_rectangle((inset * s, (5 + inset / 2) * s, w - inset * s, h - inset * s),
                               radius=26 * s, fill=(0, 0, 0, alpha))
    draw.rounded_rectangle((5 * s, 4 * s, w - 5 * s, h - 6 * s), radius=22 * s, fill=surface,
                           outline=border, width=max(1, round(s)))
    logo(draw, 19 * s, center - 10 * s, 0.94 * s, accent)
    draw.line((49 * s, center - 11 * s, 49 * s, center + 11 * s), fill=border, width=max(1, round(s)))

    blend = frame.transition
    if blend < 1:
        wave = Image.new("RGBA", im.size)
        marks = ImageDraw.Draw(wave)
        wave_alpha = round(255 * (1 - blend))
        rgb_accent = tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5))
        rgb_muted = tuple(int(muted[i:i + 2], 16) for i in (1, 3, 5))

        cur_x = 58 * s
        if frame.mode_badge:
            badge_text = frame.mode_badge.strip()
            if badge_text.endswith("…"):
                badge_text = badge_text[:-1]
            b_font = font(max(8, round(10 * s)), "Medium")
            b_text_w = b_font.getlength(badge_text)
            b_pill_w = b_text_w + 14 * s
            b_pill_h = 18 * s
            b_top = center - b_pill_h / 2
            marks.rounded_rectangle(
                (cur_x, b_top, cur_x + b_pill_w, b_top + b_pill_h),
                radius=9 * s,
                fill=(*rgb_accent, round(28 * (1 - blend))),
                outline=(*rgb_accent, round(120 * (1 - blend))),
                width=max(1, round(s)),
            )
            marks.text(
                (cur_x + b_pill_w / 2, center),
                badge_text,
                font=b_font,
                fill=(*rgb_accent, wave_alpha),
                anchor="mm",
            )
            cur_x += b_pill_w + 8 * s

        for i, bar in enumerate(waveform_heights(frame.wave_time)):
            bx = cur_x + i * 6.6 * s
            half = bar * s * (1 - 0.7 * blend) / 2
            marks.rounded_rectangle(
                (bx, center - half, bx + 2.8 * s, center + half),
                radius=1.4 * s,
                fill=(*rgb_accent, wave_alpha),
            )
        cur_x += 9 * 6.6 * s + 8 * s

        working_label = frame.label if frame.state == "working" else "Refining…"
        label_size = 12
        while label_size > 8 and font(round(label_size * s)).getlength(working_label) > (w - cur_x - 30 * s):
            label_size -= 1
        working_label = ellipsize(working_label, font(max(8, round(label_size * s))),
                                  w - cur_x - 30 * s)
        marks.text(
            (cur_x, center),
            working_label,
            font=font(max(8, round(label_size * s))),
            fill=(*rgb_muted, wave_alpha),
            anchor="lm",
        )
        im = Image.alpha_composite(im, wave)
        draw = ImageDraw.Draw(im)

    if blend > 0:
        result = Image.new("RGBA", im.size)
        marks = ImageDraw.Draw(result)
        x = 66 * s
        stroke = max(1, round(2 * s))

        if frame.state in ("success", "unchanged", "review"):
            mark = accent
        elif frame.state == "undo":
            mark = ice_blue
        else:
            mark = coral if dark else amber

        if frame.state == "success":
            marks.line(
                (x - 6 * s, center, x - 1 * s, center + 5 * s, x + 7 * s, center - 5 * s),
                fill=mark,
                width=stroke,
                joint="curve",
            )
        elif frame.state == "undo":
            marks.line((x - 4 * s, center, x + 3 * s, center, x + 5 * s, center + 4 * s),
                       fill=mark, width=stroke)
            marks.line((x - 1 * s, center - 4 * s, x - 4 * s, center, x - 1 * s, center + 4 * s),
                       fill=mark, width=stroke, joint="curve")
        elif frame.state == "unchanged":
            marks.ellipse((x - 4 * s, center - 4 * s, x + 4 * s, center + 4 * s),
                          outline=mark, width=stroke)
        else:
            marks.line((x, center - 6 * s, x, center + s), fill=mark, width=stroke)
            marks.ellipse((x - s, center + 4 * s, x + s, center + 6 * s), fill=mark)

        cur_x = 82 * s
        main_label = frame.label or ("Refined" if frame.state == "success" else "Done")
        label_font = font(max(8, round(13 * s)), "Medium")
        marks.text((cur_x, center), main_label, font=label_font, fill=ink, anchor="lm")
        cur_x += label_font.getlength(main_label) + 8 * s

        if frame.diff_badge:
            d_font = font(max(8, round(10 * s)), "Medium")
            d_text = frame.diff_badge.strip()
            d_w = d_font.getlength(d_text) + 14 * s
            d_h = 18 * s
            d_top = center - d_h / 2
            d_bg = (255, 255, 255, 18) if dark else (0, 0, 0, 14)
            d_border = border
            d_text_color = ink
            if d_text.startswith("+") or "words" in d_text:
                d_text_color = accent
                d_border = (191, 245, 73, 90) if dark else (54, 87, 22, 90)
            elif "cached" in d_text.lower():
                d_text_color = amber
                d_border = (230, 183, 121, 90) if dark else (180, 130, 40, 90)
            marks.rounded_rectangle(
                (cur_x, d_top, cur_x + d_w, d_top + d_h),
                radius=9 * s,
                fill=d_bg,
                outline=d_border,
                width=max(1, round(s)),
            )
            marks.text((cur_x + d_w / 2, center), d_text, font=d_font, fill=d_text_color, anchor="mm")
            cur_x += d_w + 6 * s

        if frame.cached and "cached" not in (frame.diff_badge or "").lower():
            c_font = font(max(8, round(9.5 * s)), "Medium")
            c_text = "Cached"
            bolt_w = 12 * s
            c_w = bolt_w + c_font.getlength(c_text) + 14 * s
            c_h = 18 * s
            c_top = center - c_h / 2
            c_bg = (230, 183, 121, 35) if dark else (240, 220, 180, 160)
            c_border = (230, 183, 121, 90) if dark else (180, 130, 40, 90)
            marks.rounded_rectangle(
                (cur_x, c_top, cur_x + c_w, c_top + c_h),
                radius=9 * s,
                fill=c_bg,
                outline=c_border,
                width=max(1, round(s)),
            )
            bolt(marks, cur_x + 5 * s, center - 7 * s, 0.85 * s, amber)
            marks.text((cur_x + bolt_w + 4 * s, center), c_text, font=c_font, fill=amber, anchor="lm")
            cur_x += c_w + 6 * s

        if frame.mode_badge and not frame.diff_badge:
            m_font = font(max(8, round(10 * s)), "Medium")
            m_text = frame.mode_badge.strip()
            if m_text.endswith("…"):
                m_text = m_text[:-1]
            m_w = m_font.getlength(m_text) + 12 * s
            m_h = 18 * s
            m_top = center - m_h / 2
            marks.rounded_rectangle(
                (cur_x, m_top, cur_x + m_w, m_top + m_h),
                radius=9 * s,
                fill=(255, 255, 255, 14) if dark else (0, 0, 0, 10),
                outline=border,
                width=max(1, round(s)),
            )
            marks.text((cur_x + m_w / 2, center), m_text, font=m_font, fill=muted, anchor="mm")
            cur_x += m_w + 6 * s

        if frame.subtext:
            sub_font = font(max(8, round(10 * s)), "Regular")
            marks.text((cur_x, center), frame.subtext, font=sub_font, fill=muted, anchor="lm")

        if frame.review:
            # [Discard] [Apply] sit right-aligned before the close zone; the
            # overlay's click zones mirror these exact rectangles.
            btn_font = font(max(8, round(10 * s)), "Medium")
            btn_h = 22 * s
            btn_top = center - btn_h / 2
            d_x0 = w - 48 * s - 152 * s
            a_x0 = w - 48 * s - 76 * s
            marks.rounded_rectangle(
                (d_x0, btn_top, d_x0 + 72 * s, btn_top + btn_h),
                radius=11 * s,
                fill=(255, 255, 255, 14) if dark else (0, 0, 0, 10),
                outline=border,
                width=max(1, round(s)),
            )
            marks.text((d_x0 + 36 * s, center), "Discard", font=btn_font, fill=muted, anchor="mm")
            marks.rounded_rectangle(
                (a_x0, btn_top, a_x0 + 72 * s, btn_top + btn_h),
                radius=11 * s,
                fill=(*tuple(int(accent[i:i + 2], 16) for i in (1, 3, 5)), 235),
            )
            marks.text((a_x0 + 36 * s, center), "Apply", font=btn_font,
                       fill=(16, 29, 73), anchor="mm")

        result.putalpha(result.getchannel("A").point(lambda value: round(value * blend)))
        im = Image.alpha_composite(im, result)
        draw = ImageDraw.Draw(im)

    x = w - 23 * s
    for direction in (-1, 1):
        draw.line((x - 3.7 * s, center - direction * 3.7 * s, x + 3.7 * s, center + direction * 3.7 * s),
                  fill=muted, width=max(1, round(1.1 * s)))
    return im.resize((width, height), Image.Resampling.LANCZOS)
