"""
Quoting section 8.2.2 "Document Outline" of the 2006 PDF spec 1.7:
> The document outline consists of a tree-structured hierarchy of outline items (sometimes called bookmarks),
> which serve as a visual table of contents to display the document’s structure to the user.

The contents of this module are internal to fpdf2, and not part of the public API.
They may change at any time without prior warning or any deprecation period,
in non-backward-compatible ways.
"""

from typing import List, NamedTuple, Optional, TYPE_CHECKING

from .enums import Align, XPos, YPos
from .fonts import FontFace
from .syntax import Destination, PDFObject, PDFString
from .structure_tree import StructElem

if TYPE_CHECKING:
    from .fpdf import FPDF


class OutlineSection(NamedTuple):
    name: str
    level: int
    page_number: int
    dest: Destination
    struct_elem: Optional[StructElem] = None


class OutlineItemDictionary(PDFObject):
    __slots__ = (  # RAM usage optimization
        "_id",
        "title",
        "parent",
        "prev",
        "next",
        "first",
        "last",
        "count",
        "dest",
        "struct_elem",
    )

    def __init__(
        self,
        title: str,
        dest: Destination = None,
        struct_elem: StructElem = None,
    ):
        super().__init__()
        self.title = PDFString(title, encrypt=True)
        self.parent = None
        self.prev = None
        self.next = None
        self.first = None
        self.last = None
        self.count = 0
        self.dest = dest
        self.struct_elem = struct_elem


class OutlineDictionary(PDFObject):
    __slots__ = ("_id", "type", "first", "last", "count")  # RAM usage optimization

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.type = "/Outlines"
        self.first = None
        self.last = None
        self.count = 0


def build_outline_objs(sections):
    """
    Build PDF objects constitutive of the documents outline,
    and yield them one by one, starting with the outline dictionary
    """
    outline = OutlineDictionary()
    yield outline
    outline_items = []
    last_outline_item_per_level = {}
    for section in sections:
        outline_item = OutlineItemDictionary(
            title=section.name,
            dest=section.dest,
            struct_elem=section.struct_elem,
        )
        yield outline_item
        if section.level in last_outline_item_per_level:
            last_outline_item_at_level = last_outline_item_per_level[section.level]
            last_outline_item_at_level.next = outline_item
            outline_item.prev = last_outline_item_at_level
        if section.level - 1 in last_outline_item_per_level:
            parent_outline_item = last_outline_item_per_level[section.level - 1]
        else:
            parent_outline_item = outline
        outline_item.parent = parent_outline_item
        if parent_outline_item.first is None:
            parent_outline_item.first = outline_item
        parent_outline_item.last = outline_item
        parent_outline_item.count += 1
        outline_items.append(outline_item)
        last_outline_item_per_level[section.level] = outline_item
        last_outline_item_per_level = {
            level: oitem
            for level, oitem in last_outline_item_per_level.items()
            if level <= section.level
        }
    return [outline] + outline_items


class TableOfContents:

    def __init__(self):
        self.title = "Table of Contents"
        self.title_style = FontFace(emphasis="B", size_pt=16)
        self.level_indent = 7.5
        self.line_spacing = 1.5
        self.ignore_pages_before_toc = True

    def render_toc_title(self, pdf: "FPDF"):
        with pdf.use_font_face(self.title_style):
            pdf.set_x(pdf.l_margin)
            pdf.multi_cell(
                w=pdf.epw,
                text=self.title,
                new_x=XPos.LMARGIN,
                new_y=YPos.NEXT,
                h=pdf.font_size * self.line_spacing,
            )
            pdf.ln()

    def render_toc_item(self, pdf: "FPDF", item: OutlineSection):
        link = pdf.add_link(page=item.page_number)
        page_label = pdf.pages[item.page_number].get_label()

        # render the text on the left
        indent = (item.level * self.level_indent) + pdf.l_margin
        pdf.set_x(indent)
        pdf.multi_cell(
            w=pdf.w - indent - pdf.r_margin,
            text=item.name,
            new_x=XPos.END,
            new_y=YPos.LAST,
            link=link,
            align=Align.J,
            h=pdf.font_size * self.line_spacing,
        )

        # fill in-between with dots
        current_x = pdf.get_x()
        page_label_length = pdf.get_string_width(page_label)
        in_between_space = pdf.w - current_x - page_label_length - pdf.r_margin
        in_between = ""
        if in_between_space > 0:
            while pdf.get_string_width(in_between + "  ") < in_between_space:
                in_between += "."

            if len(in_between) > 1:
                pdf.multi_cell(
                    w=pdf.w - current_x - pdf.r_margin,
                    text=in_between[:-1],
                    new_x=XPos.END,
                    new_y=YPos.LAST,
                    link=link,
                    align=Align.L,
                    h=pdf.font_size * self.line_spacing,
                )

        # render the page number on the right
        pdf.set_x(current_x)
        pdf.multi_cell(
            w=pdf.w - current_x - pdf.r_margin,
            text=page_label,
            new_x=XPos.END,
            new_y=YPos.LAST,
            link=link,
            align=Align.R,
            h=pdf.font_size * self.line_spacing,
        )
        pdf.ln()

    def render_toc(self, pdf: "FPDF", outline: List[OutlineSection]):
        "This method can be overriden by subclasses to customize the Table of Contents style."
        self.render_toc_title(pdf)
        for section in outline:
            if (
                self.ignore_pages_before_toc
                and section.page_number <= pdf.toc_placeholder.start_page
            ):
                continue
            self.render_toc_item(pdf, section)
