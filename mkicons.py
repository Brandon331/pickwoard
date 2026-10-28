from PIL import Image, ImageDraw
import random
def fig(draw, ox, oy, s, ss):
    P = lambda x, y: (ox + (x - 60) * s, oy + (y - 76) * s)
    def line(a, b, col, w):
        (x1, y1), (x2, y2) = P(*a), P(*b); r = w * s / 2
        draw.line([x1, y1, x2, y2], fill=col, width=int(w * s))
        for x, y in ((x1, y1), (x2, y2)): draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
    for a, b in (((46, 22), (40, 8)), ((60, 18), (60, 3)), ((74, 22), (80, 8))): line(a, b, "#e8281e", 6)
    cx, cy = P(60, 40); R = 20 * s; draw.ellipse([cx - R, cy - R, cx + R, cy + R], outline="#f5821f", width=int(7 * s))
    for ex in (52, 68):
        x, y = P(ex, 35); r = 3.2 * s; draw.ellipse([x - r, y - r, x + r, y + r], fill="#2a1a14")
    (x1, y1), (x2, y2) = P(49, 36), P(71, 56); draw.arc([x1, y1, x2, y2], 25, 155, fill="#e0338a", width=int(5 * s))
    line((60, 61), (60, 108), "#ffffff", 7)            # cuerpo en blanco para que resalte sobre el azul
    line((60, 72), (32, 96), "#ffe21f", 7); line((60, 72), (88, 96), "#ffe21f", 7)
    line((60, 108), (40, 148), "#9bc53d", 7); line((60, 108), (80, 148), "#9bc53d", 7)
def make(size, scale, rounded, name):
    ss = 4; W = size * ss
    im = Image.new("RGBA", (W, W), "#2f7fd8"); d = ImageDraw.Draw(im, "RGBA"); rnd = random.Random(5)
    for _ in range(140):                                # trazos de crayón suaves
        x, y = rnd.random() * W, rnd.random() * W; a = rnd.random() * 3.14; l = W * (.08 + rnd.random() * .14)
        col = rnd.choice([(90, 165, 240, 70), (31, 98, 184, 70), (255, 255, 255, 28)])
        d.line([x, y, x + l * 0.9 * (1 if a < 1.6 else -1), y + l * 0.4 * (1 if a % 1 < .5 else -1)], fill=col, width=int(W * .018))
    fig(d, W / 2, W / 2 + W * .005, scale * ss, ss)
    if rounded:
        m = Image.new("L", (W, W), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, W - 1, W - 1], radius=int(W * .22), fill=255)
        bg = Image.new("RGBA", (W, W), (0, 0, 0, 0)); bg.paste(im, mask=m); im = bg
    im.resize((size, size), Image.LANCZOS).save(name)
make(512, 2.75, True, "icon-512.png"); make(192, 2.75 * 192 / 512, True, "icon-192.png")
make(512, 2.05, False, "icon-maskable-512.png"); make(180, 2.3 * 180 / 512, False, "apple-touch-icon.png")
print("iconos ok")