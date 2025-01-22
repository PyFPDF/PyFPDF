import logging

from typing import List, Tuple, TYPE_CHECKING
from io import BytesIO
from fontTools.ttLib.tables.BitmapGlyphMetrics import BigGlyphMetrics, SmallGlyphMetrics

from .drawing import DeviceRGB, GraphicsContext, Transform, PathPen, PaintedPath


if TYPE_CHECKING:
    from .fpdf import FPDF
    from .fonts import TTFFont


LOGGER = logging.getLogger(__name__)


class Type3FontGlyph:
    # RAM usage optimization:
    __slots__ = (
        "obj_id",
        "glyph_id",
        "unicode",
        "glyph_name",
        "glyph_width",
        "glyph",
        "_glyph_bounds",
    )
    obj_id: int
    glyph_id: int
    unicode: Tuple
    glyph_name: str
    glyph_width: int
    glyph: str
    _glyph_bounds: Tuple[int, int, int, int]

    def __init__(self):
        pass

    def __hash__(self):
        return self.glyph_id


class Type3Font:

    def __init__(self, fpdf: "FPDF", base_font: "TTFFont"):
        self.i = 1
        self.type = "type3"
        self.fpdf = fpdf
        self.base_font = base_font
        self.upem = self.base_font.ttfont["head"].unitsPerEm
        self.scale = 1000 / self.upem
        self.images_used = set()
        self.graphics_style_used = set()
        self.glyphs: List[Type3FontGlyph] = []

    def get_notdef_glyph(self, glyph_id) -> Type3FontGlyph:
        notdef = Type3FontGlyph()
        notdef.glyph_id = glyph_id
        notdef.unicode = glyph_id
        notdef.glyph_name = ".notdef"
        notdef.glyph_width = self.base_font.cw[0x00] if self.base_font.cw[0x00] else 0
        notdef.glyph = f"{notdef.glyph_width} 0 d0"
        return notdef

    def get_space_glyph(self, glyph_id) -> Type3FontGlyph:
        space = Type3FontGlyph()
        space.glyph_id = glyph_id
        space.unicode = 0x20
        space.glyph_name = "space"
        space_width = (
            self.base_font.cw[0x20]
            if self.base_font.cw[0x20]
            else self.base_font.ttfont["hmtx"].metrics[".notdef"][0]
        )
        space.glyph_width = space_width
        space.glyph = f"{space.glyph_width} 0 d0"
        return space

    def load_glyphs(self):
        for glyph, char_id in self.base_font.subset.items():
            if not self.glyph_exists(glyph.glyph_name):
                if char_id == 0x20 or glyph.glyph_name == "space":
                    print("is space")
                    self.glyphs.append(self.get_space_glyph(char_id))
                    continue
                if self.glyph_exists(".notdef"):
                    self.add_glyph(".notdef", char_id)
                    continue
                self.glyphs.append(self.get_notdef_glyph(char_id))
                continue
            self.add_glyph(glyph.glyph_name, char_id)

    def add_glyph(self, glyph_name, char_id):
        g = Type3FontGlyph()
        g.glyph_id = char_id
        g.unicode = char_id
        g.glyph_name = glyph_name
        self.load_glyph_image(g)
        self.glyphs.append(g)

    @classmethod
    def get_target_ppem(cls, font_size_pt: int) -> int:
        # Calculating the target ppem:
        # https://learn.microsoft.com/en-us/typography/opentype/spec/ttch01#display-device-characteristics
        # ppem = point_size * dpi / 72
        # The default PDF dpi resolution is 72 dpi - and we have the 72 dpi hardcoded on our scale factor,
        # so we can simplify the calculation.
        return font_size_pt

    def load_glyph_image(self, glyph: Type3FontGlyph):
        raise NotImplementedError("Method must be implemented on child class")

    def glyph_exists(self, glyph_name: str) -> bool:
        raise NotImplementedError("Method must be implemented on child class")


class SVGColorFont(Type3Font):

    def glyph_exists(self, glyph_name):
        glyph_id = self.base_font.ttfont.getGlyphID(glyph_name)
        return any(
            svg_doc.startGlyphID <= glyph_id <= svg_doc.endGlyphID
            for svg_doc in self.base_font.ttfont["SVG "].docList
        )

    def load_glyph_image(self, glyph: Type3FontGlyph):
        glyph_id = self.base_font.ttfont.getGlyphID(glyph.glyph_name)
        glyph_svg_data = None
        for svg_doc in self.base_font.ttfont["SVG "].docList:
            if svg_doc.startGlyphID <= glyph_id <= svg_doc.endGlyphID:
                glyph_svg_data = svg_doc.data.encode("utf-8")
                break
        bio = BytesIO(glyph_svg_data)
        bio.seek(0)
        _, img, _ = self.fpdf.preload_image(bio, None)
        w = round(self.base_font.ttfont["hmtx"].metrics[glyph.glyph_name][0] + 0.001)
        # img.base_group.transform = Transform.identity()
        img.base_group.transform = Transform.scaling(self.scale, self.scale)
        output_stream = self.fpdf.draw_vector_glyph(img.base_group, self)
        glyph.glyph = (
            f"{w * self.scale / self.upem} 0 d0\n" "q\n" f"{output_stream}\n" "Q"
        )
        glyph.glyph_width = w


class COLRFont(Type3Font):

    def glyph_exists(self, glyph_name):
        return glyph_name in self.base_font.ttfont["COLR"].ColorLayers

    def load_glyph_image(self, glyph: Type3FontGlyph):
        w = round(self.base_font.ttfont["hmtx"].metrics[glyph.glyph_name][0] + 0.001)
        glyph_layers = self.base_font.ttfont["COLR"].ColorLayers[glyph.glyph_name]
        img = self.draw_glyph_colrv0(glyph_layers)
        img.transform = Transform.scaling(self.scale, -self.scale)
        output_stream = self.fpdf.draw_vector_glyph(img, self)
        glyph.glyph = (
            f"{w * self.scale / self.upem} 0 d0\n" "q\n" f"{output_stream}\n" "Q"
        )
        glyph.glyph_width = w

    def get_color(self, color_index, palette=0):
        palettes = [
            [(c.red / 255, c.green / 255, c.blue / 255, c.alpha / 255) for c in p]
            for p in self.base_font.ttfont["CPAL"].palettes
        ]
        r, g, b, a = palettes[palette][color_index]
        # a *= alpha
        return DeviceRGB(r, g, b, a)

    def draw_glyph_colrv0(self, layers):
        gc = GraphicsContext()
        for layer in layers:
            print(layer.__repr__)
            print(layer.colorID, layer.name)
            path = PaintedPath()
            glyph_set = self.base_font.ttfont.getGlyphSet()
            pen = PathPen(path, glyphSet=glyph_set)
            glyph = glyph_set[layer.name]
            glyph.draw(pen)
            path.style.fill_color = self.get_color(layer.colorID)
            path.style.stroke_color = self.get_color(layer.colorID)
            gc.add_item(path)
        return gc
        # print(path)
        # self.base_font.hbfont.draw_glyph_with_pen(gid, path)
        # canvas.drawPathSolid(path, self._getColor(layer.colorID, 1))


class CBDTColorFont(Type3Font):

    # Only looking at the first strike - Need to look all strikes available on the CBLC table first?

    def glyph_exists(self, glyph_name):
        return glyph_name in self.base_font.ttfont["CBDT"].strikeData[0]

    def load_glyph_image(self, glyph_name):
        ppem = self.base_font.ttfont["CBLC"].strikes[0].bitmapSizeTable.ppemX
        glyph = self.base_font.ttfont["CBDT"].strikeData[0][glyph_name]
        glyph_bitmap = glyph.data[9:]
        metrics = glyph.metrics
        if isinstance(metrics, SmallGlyphMetrics):
            x_min = round(metrics.BearingX * self.upem / ppem)
            y_min = round((metrics.BearingY - metrics.height) * self.upem / ppem)
            x_max = round(metrics.width * self.upem / ppem)
            y_max = round(metrics.BearingY * self.upem / ppem)
        elif isinstance(metrics, BigGlyphMetrics):
            x_min = round(metrics.horiBearingX * self.upem / ppem)
            y_min = round((metrics.horiBearingY - metrics.height) * self.upem / ppem)
            x_max = round(metrics.width * self.upem / ppem)
            y_max = round(metrics.horiBearingY * self.upem / ppem)
        else:  # fallback scenario: use font bounding box
            x_min = self.base_font.ttfont["head"].xMin
            y_min = self.base_font.ttfont["head"].yNin
            x_max = self.base_font.ttfont["head"].xMax
            y_max = self.base_font.ttfont["head"].yMax

        bio = BytesIO(glyph_bitmap)
        bio.seek(0)
        _, _, info = self.fpdf.preload_image(bio, None)
        w = round(self.base_font.ttfont["hmtx"].metrics[glyph.glyph_name][0] + 0.001)
        glyph.glyph = (
            f"{w / self.scale} 0 d0\n"
            "q\n"
            f"{(x_max - x_min)* self.scale} 0 0 {(-y_min + y_max)*self.scale} {x_min*self.scale} {y_min*self.scale} cm\n"
            f"/I{info['i']} Do\nQ"
        )
        self.images_used.add(info["i"])
        glyph.glyph_width = w


class SBIXColorFont(Type3Font):

    def glyph_exists(self, glyph_name):
        glyph = (
            self.base_font.ttfont["sbix"]
            .strikes[self.get_strike_index()]
            .glyphs.get(glyph_name)
        )
        return glyph and glyph.graphicType

    def get_strike_index(self):
        target_ppem = self.get_target_ppem(self.base_font.biggest_size_pt)
        ppem_list = [
            ppem
            for ppem in self.base_font.ttfont["sbix"].strikes.keys()
            if ppem >= target_ppem
        ]
        if not ppem_list:
            return max(list(self.base_font.ttfont["sbix"].strikes.keys()))
        return min(ppem_list)

    def load_glyph_image(self, glyph: Type3FontGlyph):
        ppem = self.get_strike_index()
        sbix_glyph = (
            self.base_font.ttfont["sbix"].strikes[ppem].glyphs.get(glyph.glyph_name)
        )
        if sbix_glyph.graphicType == "dupe":
            raise NotImplementedError(
                f"{glyph.glyph_name}: Dupe SBIX graphic type not implemented."
            )
            # waiting for an example to test
            # dupe_char = font.getBestCmap()[glyph.imageData]
            # return self.get_color_glyph(dupe_char)

        if sbix_glyph.graphicType not in ("jpg ", "png ", "tiff"):  # pdf or mask
            raise NotImplementedError(
                f" {glyph.glyph_name}: Invalid SBIX graphic type {sbix_glyph.graphicType}."
            )

        bio = BytesIO(sbix_glyph.imageData)
        bio.seek(0)
        _, _, info = self.fpdf.preload_image(bio, None)
        w = round(self.base_font.ttfont["hmtx"].metrics[glyph.glyph_name][0] + 0.001)
        glyf_metrics = self.base_font.ttfont["glyf"].get(glyph.glyph_name)
        x_min = glyf_metrics.xMin + sbix_glyph.originOffsetX
        x_max = glyf_metrics.xMax + sbix_glyph.originOffsetX
        y_min = glyf_metrics.yMin + sbix_glyph.originOffsetY
        y_max = glyf_metrics.yMax + sbix_glyph.originOffsetY

        glyph.glyph = (
            f"{(x_max - x_min) * self.scale} 0 d0\n"
            "q\n"
            f"{(x_max - x_min) * self.scale} 0 0 {(-y_min + y_max) * self.scale} {x_min * self.scale} {y_min * self.scale} cm\n"
            f"/I{info['i']} Do\nQ"
        )
        self.images_used.add(info["i"])
        glyph.glyph_width = w


# pylint: disable=too-many-return-statements
def get_color_font_object(fpdf: "FPDF", base_font: "TTFFont") -> Type3Font:
    if "CBDT" in base_font.ttfont:
        LOGGER.warning("Font %s is a CBLC+CBDT color font", base_font.name)
        return CBDTColorFont(fpdf, base_font)
    if "EBDT" in base_font.ttfont:
        LOGGER.warning("%s - EBLC+EBDT color font is not supported yet", base_font.name)
        return None
    if "COLR" in base_font.ttfont:
        if base_font.ttfont["COLR"].version == 0:
            LOGGER.warning("Font %s is a COLRv0 color font", base_font.name)
            return COLRFont(fpdf, base_font)
        LOGGER.warning("Font %s is a COLRv1 color font", base_font.name)
        return None
    if "SVG " in base_font.ttfont:
        LOGGER.warning("Font %s is a SVG color font", base_font.name)
        return SVGColorFont(fpdf, base_font)
    if "sbix" in base_font.ttfont:
        LOGGER.warning("Font %s is a SBIX color font", base_font.name)
        return SBIXColorFont(fpdf, base_font)
    return None
