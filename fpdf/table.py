from dataclasses import dataclass
from numbers import Number
from typing import Optional, Union, Tuple, Sequence, Protocol

from .enums import Align, TableCellFillMode, WrapMode, VAlign
from .enums import MethodReturnValue
from .errors import FPDFException
from .fonts import CORE_FONTS, FontFace
from .util import Padding
from .drawing import DeviceGray, DeviceRGB

DEFAULT_HEADINGS_STYLE = FontFace(emphasis="BOLD")


def wrap_in_local_context(draw_commands):
    return ["q"] + draw_commands + ["Q"]


def convert_to_drawing_color(color):
    if isinstance(color, (DeviceGray, DeviceRGB)):
        # Note: in this case, r is also a Sequence
        return color
    if isinstance(color, int):
        return DeviceGray(color / 255)
    if isinstance(color, Sequence):
        return DeviceRGB(*(_x / 255 for _x in color))
    raise ValueError(f"Unsupported color type: {type(color)}")


@dataclass(slots=True)
class TableBorderStyle:
    """
    A helper class for drawing one border of a table

    Attributes:
        thickness: The thickness of the border. If None use default. If <= 0 don't draw the border.
        color: The color of the border. If None use default.
    """

    thickness: Optional[float] = None
    color: Union[int, Tuple[int, int, int]] = None
    dash: Optional[float] = None
    gap: float = 0.0
    phase: float = 0.0

    @staticmethod
    def from_bool(should_draw):
        if isinstance(should_draw, TableBorderStyle):
            return should_draw  # don't change specified TableBorderStyle
        if should_draw:
            return TableBorderStyle()  # keep default stroke
        return TableBorderStyle(thickness=0.0)  # don't draw the border

    def _changes_thickness(self, pdf):
        return (
            self.thickness is not None
            and self.thickness > 0.0
            and self.thickness != pdf.line_width
        )

    def _changes_color(self, pdf):
        return self.color is not None and self.color != pdf.draw_color

    @property
    def dash_dict(self):
        return {"dash": self.dash, "gap": self.gap, "phase": self.phase}

    def _changes_dash(self, pdf):
        return self.dash is not None and self.dash_dict != pdf.dash

    def changes_stroke(self, pdf):
        return self.should_render() and (
            self._changes_color(pdf)
            or self._changes_thickness(pdf)
            or self._changes_dash(pdf)
        )

    def should_render(self):
        return self.thickness is None or self.thickness > 0.0

    def _get_change_thickness_command(self, scale):
        return [] if self.thickness is None else [f"{self.thickness * scale:.2f} w"]

    def _get_change_line_color_command(self):
        return (
            []
            if self.color is None
            else [convert_to_drawing_color(self.color).serialize().upper()]
        )

    def _get_change_dash_command(self, scale):
        return (
            []
            if self.dash is None
            else [
                "[] 0 d"
                if self.dash <= 0
                else f"[{self.dash * scale:.3f}] {self.phase * scale:.3f} d"
                if self.gap <= 0
                else f"[{self.dash * scale:.3f} {self.gap * scale:.3f}] {self.phase * scale:.3f} d"
            ]
        )

    def get_change_stroke_commands(self, scale):
        return (
            self._get_change_dash_command(scale)
            + self._get_change_line_color_command()
            + self._get_change_thickness_command(scale)
        )

    @staticmethod
    def get_line_command(x1, y1, x2, y2):
        return [f"{x1:.2f} {y1:.2f} m " f"{x2:.2f} {y2:.2f} l S"]

    def get_draw_commands(self, pdf, x1, y1, x2, y2):
        """
        Get draw commands for this section of a cell border. x and y are presumed to be already
        shifted and scaled.
        """
        if not self.should_render():
            return []

        if self.changes_stroke(pdf):
            draw_commands = self.get_change_stroke_commands(
                scale=pdf.k
            ) + self.get_line_command(x1, y1, x2, y2)
            # wrap in local context to prevent stroke changes from affecting later rendering
            return wrap_in_local_context(draw_commands)
        return self.get_line_command(x1, y1, x2, y2)


@dataclass(slots=True)
class TableCellStyle:
    left: Union[bool, TableBorderStyle] = False
    bottom: Union[bool, TableBorderStyle] = False
    right: Union[bool, TableBorderStyle] = False
    top: Union[bool, TableBorderStyle] = False

    def _get_common_border_style(self):
        if all(
            isinstance(border, bool)
            for border in [self.left, self.bottom, self.right, self.top]
        ):
            if all(border for border in [self.left, self.bottom, self.right, self.top]):
                return True
            if all(
                not border for border in [self.left, self.bottom, self.right, self.top]
            ):
                return False
        elif all(
            isinstance(border, TableBorderStyle)
            for border in [self.left, self.bottom, self.right, self.top]
        ):
            common = self.left
            if all(border == common for border in [self.bottom, self.right, self.top]):
                return common
        return None

    @staticmethod
    def get_change_fill_color_command(color):
        return (
            []
            if color is None
            else [convert_to_drawing_color(color).serialize().lower()]
        )

    def get_draw_commands(self, pdf, x1, y1, x2, y2, fill_color=None):
        """
        Get list of primitive commands to draw the cell border for this cell, and fill it with the
        given fill color.
        """
        # y top to bottom instead of bottom to top
        y1 = pdf.h - y1
        y2 = pdf.h - y2
        # scale coordinates and thickness
        scale = pdf.k
        x1 *= scale
        y1 *= scale
        x2 *= scale
        y2 *= scale

        draw_commands = []
        needs_wrap = False
        common_border_style = self._get_common_border_style()
        if common_border_style is None:
            # some borders are different from others, draw them individually
            if fill_color is not None:
                # draw fill with no box
                if fill_color != pdf.fill_color:
                    needs_wrap = True
                    draw_commands.extend(self.get_change_fill_color_command(fill_color))
                draw_commands.append(
                    f"{x1:.2f} {y2:.2f} " f"{x2 - x1:.2f} {y1 - y2:.2f} re f"
                )
            # draw the individual borders
            draw_commands.extend(
                TableBorderStyle.from_bool(self.left).get_draw_commands(
                    pdf, x1, y2, x1, y1
                )
                + TableBorderStyle.from_bool(self.bottom).get_draw_commands(
                    pdf, x1, y2, x2, y2
                )
                + TableBorderStyle.from_bool(self.right).get_draw_commands(
                    pdf, x2, y2, x2, y1
                )
                + TableBorderStyle.from_bool(self.top).get_draw_commands(
                    pdf, x1, y1, x2, y1
                )
            )
        elif common_border_style is False:
            # don't draw border
            if fill_color is not None:
                # draw fill with no box
                if fill_color != pdf.fill_color:
                    needs_wrap = True
                    draw_commands.extend(self.get_change_fill_color_command(fill_color))
                draw_commands.append(
                    f"{x1:.2f} {y2:.2f} " f"{x2 - x1:.2f} {y1 - y2:.2f} re f"
                )
        else:
            # all borders are the same
            if isinstance(
                common_border_style, TableBorderStyle
            ) and common_border_style.changes_stroke(pdf):
                # the border styles aren't default, so
                draw_commands.extend(
                    common_border_style.get_change_stroke_commands(scale)
                )
                needs_wrap = True
            if fill_color is not None:
                # draw filled rectangle
                if fill_color != pdf.fill_color:
                    needs_wrap = True
                    draw_commands.extend(self.get_change_fill_color_command(fill_color))
                draw_commands.append(
                    f"{x1:.2f} {y2:.2f} " f"{x2 - x1:.2f} {y1 - y2:.2f} re B"
                )
            else:
                # draw empty rectangle
                draw_commands.append(
                    f"{x1:.2f} {y2:.2f} " f"{x2 - x1:.2f} {y1 - y2:.2f} re S"
                )

        if needs_wrap:
            draw_commands = wrap_in_local_context(draw_commands)
        return draw_commands

    def draw_cell_border(self, pdf, x1, y1, x2, y2, fill_color=None):
        """
        Draw the cell border for this cell, and fill it with the given fill color.
        """
        pdf._out(  # pylint: disable=protected-access
            " ".join(self.get_draw_commands(pdf, x1, y1, x2, y2, fill_color=fill_color))
        )


class CallStyleGetter(Protocol):
    def __call__(
        self,
        row_num: int,
        col_num: int,
        num_heading_rows: int,
        num_rows: int,
        num_cols: int,
    ) -> TableCellStyle:
        ...


@dataclass(slots=True)
class TableBordersLayout:
    """
    Customizable class for setting the drawing style of cell borders for the whole table.
    Standard TableBordersLayouts are available as static members of this class

    Attributes:
        cell_style_getter: a callable that takes row_num, column_num,
            num_heading_rows, num_rows, num_columns; and returns the drawing style of
            the cell border (as a TableCellStyle object)
        ALL: static TableBordersLayout that draws all table cells borders
        NONE: static TableBordersLayout that draws no table cells borders
        INTERNAL: static TableBordersLayout that draws only internal horizontal & vertical borders
        MINIMAL: static TableBordersLayout that draws only the top horizontal border, below the
            headings, and internal vertical borders
        HORIZONTAL_LINES: static TableBordersLayout that draws only horizontal lines
        NO_HORIZONTAL_LINES: static TableBordersLayout that draws all cells border except interior
            horizontal lines after the headings
        SINGLE_TOP_LINE: static TableBordersLayout that draws only the top horizontal border, below
            the headings
    """

    cell_style_getter: CallStyleGetter

    @classmethod
    def coerce(cls, value):
        """
        Attempt to coerce `value` into a member of this class.

        If value is already a member of this enumeration it is returned unchanged.
        Otherwise, if it is a string, attempt to convert it as an enumeration value. If
        that fails, attempt to convert it (case insensitively, by upcasing) as an
        enumeration name.

        If all different conversion attempts fail, an exception is raised.

        Args:
            value (Enum, str): the value to be coerced.

        Raises:
            ValueError: if `value` is a string but neither a member by name nor value.
            TypeError: if `value`'s type is neither a member of the enumeration nor a
                string.
        """

        if isinstance(value, cls):
            return value

        if isinstance(value, str):
            try:
                coerced_value = getattr(cls, value.upper())
                if isinstance(coerced_value, cls):
                    return coerced_value
            except ValueError:
                pass

        raise ValueError(f"{value} is not a valid {cls.__name__}")


# Draw all table cells borders
TableBordersLayout.ALL = TableBordersLayout(
    cell_style_getter=lambda row_num, col_num, num_heading_rows, num_rows, num_cols: TableCellStyle(
        left=True, bottom=True, right=True, top=True
    )
)
# Draw zero cells border
TableBordersLayout.NONE = TableBordersLayout(
    cell_style_getter=lambda row_num, col_num, num_heading_rows, num_rows, num_cols: TableCellStyle(
        left=False, bottom=False, right=False, top=False
    )
)
# Draw only internal horizontal & vertical borders
TableBordersLayout.INTERNAL = TableBordersLayout(
    cell_style_getter=lambda row_num, col_num, num_heading_rows, num_rows, num_cols: TableCellStyle(
        left=col_num > 0,
        bottom=col_num < num_cols - 1,
        right=row_num < num_rows - 1,
        top=row_num > 0,
    )
)
# Draw only the top horizontal border, below the headings, and internal vertical borders
TableBordersLayout.MINIMAL = TableBordersLayout(
    cell_style_getter=lambda row_num, col_num, num_heading_rows, num_rows, num_cols: TableCellStyle(
        left=col_num > 0,
        bottom=row_num < num_heading_rows,
        right=col_num < num_cols - 1,  # could remove (set False)
        top=0 < row_num <= num_heading_rows,  # could remove (set False)
    )
)
# Draw only horizontal lines
TableBordersLayout.HORIZONTAL_LINES = TableBordersLayout(
    cell_style_getter=lambda row_num, col_num, num_heading_rows, num_rows, num_cols: TableCellStyle(
        left=False, bottom=row_num < num_heading_rows - 1, right=False, top=row_num > 0
    )
)
# Draw all cells border except interior horizontal lines after the headings
TableBordersLayout.NO_HORIZONTAL_LINES = TableBordersLayout(
    cell_style_getter=lambda row_num, col_num, num_heading_rows, num_rows, num_cols: TableCellStyle(
        left=True,
        bottom=row_num == num_rows - 1,
        right=True,
        top=row_num <= num_heading_rows,
    )
)
TableBordersLayout.SINGLE_TOP_LINE = TableBordersLayout(
    cell_style_getter=lambda row_num, col_num, num_heading_rows, num_rows, num_cols: TableCellStyle(
        left=False,
        bottom=row_num <= num_heading_rows - 1,
        right=False,
        top=False,
    )
)


def draw_box_borders(pdf, x1, y1, x2, y2, border, fill_color=None):
    """Draws a box using the provided style - private helper used by table for drawing the cell and table borders.
    Difference between this and rect() is that border can be defined as "L,R,T,B" to draw only some of the four borders;
    compatible with get_border(i,k)

    See Also: rect()"""

    if fill_color:
        prev_fill_color = pdf.fill_color
        if isinstance(fill_color, (int, float)):
            fill_color = [fill_color]
        pdf.set_fill_color(*fill_color)

    sl = []

    k = pdf.k

    # y top to bottom instead of bottom to top
    y1 = pdf.h - y1
    y2 = pdf.h - y2

    # scale
    x1 *= k
    x2 *= k
    y2 *= k
    y1 *= k

    if fill_color:
        op = "B" if border == 1 else "f"
        sl.append(f"{x1:.2f} {y2:.2f} " f"{x2 - x1:.2f} {y1 - y2:.2f} re {op}")
    elif border == 1:
        sl.append(f"{x1:.2f} {y2:.2f} " f"{x2 - x1:.2f} {y1 - y2:.2f} re S")

    if isinstance(border, str):
        if "L" in border:
            sl.append(f"{x1:.2f} {y2:.2f} m " f"{x1:.2f} {y1:.2f} l S")
        if "B" in border:
            sl.append(f"{x1:.2f} {y2:.2f} m " f"{x2:.2f} {y2:.2f} l S")
        if "R" in border:
            sl.append(f"{x2:.2f} {y2:.2f} m " f"{x2:.2f} {y1:.2f} l S")
        if "T" in border:
            sl.append(f"{x1:.2f} {y1:.2f} m " f"{x2:.2f} {y1:.2f} l S")

    s = " ".join(sl)
    pdf._out(s)  # pylint: disable=protected-access

    if fill_color:
        pdf.set_fill_color(prev_fill_color)


@dataclass(frozen=True)
class RowLayoutInfo:
    height: float
    triggers_page_jump: bool
    rendered_height: dict


class Table:
    """
    Object that `fpdf.FPDF.table()` yields, used to build a table in the document.
    Detailed usage documentation: https://py-pdf.github.io/fpdf2/Tables.html
    """

    def __init__(
        self,
        fpdf,
        rows=(),
        *,
        align="CENTER",
        v_align="MIDDLE",
        borders_layout=TableBordersLayout.ALL,
        cell_fill_color=None,
        cell_fill_mode=TableCellFillMode.NONE,
        col_widths=None,
        first_row_as_headings=True,
        gutter_height=0,
        gutter_width=0,
        headings_style=DEFAULT_HEADINGS_STYLE,
        line_height=None,
        markdown=False,
        text_align="JUSTIFY",
        width=None,
        wrapmode=WrapMode.WORD,
        padding=None,
        outer_border_width=None,
        num_heading_rows=1,
    ):
        """
        Args:
            fpdf (fpdf.FPDF): FPDF current instance
            rows: optional. Sequence of rows (iterable) of str to initiate the table cells with text content
            align (str, fpdf.enums.Align): optional, default to CENTER. Sets the table horizontal position relative to the page,
                when it's not using the full page width
            borders_layout (str, fpdf.enums.TableBordersLayout): optional, default to ALL. Control what cell borders are drawn
            cell_fill_color (float, tuple, fpdf.drawing.DeviceGray, fpdf.drawing.DeviceRGB): optional.
                Defines the cells background color
            cell_fill_mode (str, fpdf.enums.TableCellFillMode): optional. Defines which cells are filled with color in the background
            col_widths (float, tuple): optional. Sets column width. Can be a single number or a sequence of numbers
            first_row_as_headings (bool): optional, default to True. If False, the first row of the table
                is not styled differently from the others
            gutter_height (float): optional vertical space between rows
            gutter_width (float): optional horizontal space between columns
            headings_style (fpdf.fonts.FontFace): optional, default to bold.
                Defines the visual style of the top headings row: size, color, emphasis...
            line_height (number): optional. Defines how much vertical space a line of text will occupy
            markdown (bool): optional, default to False. Enable markdown interpretation of cells textual content
            text_align (str, fpdf.enums.Align, tuple): optional, default to JUSTIFY. Control text alignment inside cells.
            v_align (str, fpdf.enums.AlignV): optional, default to CENTER. Control vertical alignment of cells content
            width (number): optional. Sets the table width
            wrapmode (fpdf.enums.WrapMode): "WORD" for word based line wrapping (default),
                "CHAR" for character based line wrapping.
            padding (number, tuple, Padding): optional. Sets the cell padding. Can be a single number or a sequence of numbers, default:0
                If padding for left and right ends up being non-zero then c_margin is ignored.
            outer_border_width (number): optional. Sets the width of the outer borders of the table.
                Only relevant when borders_layout is ALL or NO_HORIZONTAL_LINES. Otherwise, the border widths are controlled by FPDF.set_line_width()
            num_heading_rows (number): optional. Sets the number of heading rows, default value is 1. If this value is not 1,
                first_row_as_headings needs to be True if num_heading_rows>1 and False if num_heading_rows=0. For backwards compatibility,
                first_row_as_headings is used in case num_heading_rows is 1.
        """
        self._fpdf = fpdf
        self._align = align
        self._v_align = VAlign.coerce(v_align)
        self._borders_layout = TableBordersLayout.coerce(borders_layout)
        self._outer_border_width = outer_border_width
        self._cell_fill_color = cell_fill_color
        self._cell_fill_mode = TableCellFillMode.coerce(cell_fill_mode)
        self._col_widths = col_widths
        self._first_row_as_headings = first_row_as_headings
        self._gutter_height = gutter_height
        self._gutter_width = gutter_width
        self._headings_style = headings_style
        self._line_height = 2 * fpdf.font_size if line_height is None else line_height
        self._markdown = markdown
        self._text_align = text_align
        self._width = fpdf.epw if width is None else width
        self._wrapmode = wrapmode
        self._num_heading_rows = num_heading_rows
        self.rows = []

        if padding is None:
            self._padding = Padding.new(0)
        else:
            self._padding = Padding.new(padding)

        # check table_border_layout and outer_border_width
        if self._borders_layout not in (
            TableBordersLayout.ALL,
            TableBordersLayout.NO_HORIZONTAL_LINES,
        ):
            if outer_border_width is not None:
                raise ValueError(
                    "outer_border_width is only allowed when borders_layout is ALL or NO_HORIZONTAL_LINES"
                )
            self._outer_border_width = 0

        # check first_row_as_headings for non-default case num_heading_rows != 1
        if self._num_heading_rows != 1:
            if self._num_heading_rows == 0 and self._first_row_as_headings:
                raise ValueError(
                    "first_row_as_headings needs to be False if num_heading_rows == 0"
                )
            if self._num_heading_rows > 1 and not self._first_row_as_headings:
                raise ValueError(
                    "first_row_as_headings needs to be True if num_heading_rows > 0"
                )
        # for backwards compatibility, we respect the value of first_row_as_headings when num_heading_rows==1
        else:
            if not self._first_row_as_headings:
                self._num_heading_rows = 0

        for row in rows:
            self.row(row)

    def row(self, cells=()):
        "Adds a row to the table. Yields a `Row` object."
        row = Row(self._fpdf)
        self.rows.append(row)
        for cell in cells:
            row.cell(cell)
        return row

    def render(self):
        "This is an internal method called by `fpdf.FPDF.table()` once the table is finished"
        # Starting with some sanity checks:
        if self._width > self._fpdf.epw:
            raise ValueError(
                f"Invalid value provided width={self._width}: effective page width is {self._fpdf.epw}"
            )
        table_align = Align.coerce(self._align)
        if table_align == Align.J:
            raise ValueError(
                "JUSTIFY is an invalid value for FPDF.table() 'align' parameter"
            )
        if self._num_heading_rows > 0:
            if not self._headings_style:
                raise ValueError(
                    "headings_style must be provided to FPDF.table() if num_heading_rows>1 or first_row_as_headings=True"
                )
            emphasis = self._headings_style.emphasis
            if emphasis is not None:
                family = self._headings_style.family or self._fpdf.font_family
                font_key = family.lower() + emphasis.style
                if font_key not in CORE_FONTS and font_key not in self._fpdf.fonts:
                    # Raising a more explicit error than the one from set_font():
                    raise FPDFException(
                        f"Using font emphasis '{emphasis.style}' in table headings require the corresponding font style to be added using add_font()"
                    )
        if self.rows:
            cols_count = self.rows[0].cols_count
            for i, row in enumerate(self.rows[1:], start=2):
                if row.cols_count != cols_count:
                    raise FPDFException(
                        f"Inconsistent column count detected on row {i}:"
                        f" it has {row.cols_count} columns,"
                        f" whereas the top row has {cols_count}."
                    )

        # Defining table global horizontal position:
        prev_l_margin = self._fpdf.l_margin
        if table_align == Align.C:
            self._fpdf.l_margin = (self._fpdf.w - self._width) / 2
            self._fpdf.x = self._fpdf.l_margin
        elif table_align == Align.R:
            self._fpdf.l_margin = self._fpdf.w - self._fpdf.r_margin - self._width
            self._fpdf.x = self._fpdf.l_margin
        elif self._fpdf.x != self._fpdf.l_margin:
            self._fpdf.l_margin = self._fpdf.x

        # Pre-Compute the relative x-positions of the individual columns:
        cell_x_positions = [0]
        if self.rows:
            xx = 0
            for i in range(self.rows[0].cols_count):
                xx += self._get_col_width(0, i)
                xx += self._gutter_width
                cell_x_positions.append(xx)

        # Starting the actual rows & cells rendering:
        for i in range(len(self.rows)):
            row_layout_info = self._get_row_layout_info(i)
            if row_layout_info.triggers_page_jump:
                # pylint: disable=protected-access
                self._fpdf._perform_page_break()
                # repeat headings on top:
                for row_idx in range(self._num_heading_rows):
                    self._render_table_row(
                        row_idx,
                        self._get_row_layout_info(row_idx),
                        cell_x_positions=cell_x_positions,
                    )
            elif i and self._gutter_height:
                self._fpdf.y += self._gutter_height
            self._render_table_row(
                i, row_layout_info, cell_x_positions=cell_x_positions
            )
        # Restoring altered FPDF settings:
        self._fpdf.l_margin = prev_l_margin
        self._fpdf.x = self._fpdf.l_margin

    def get_cell_border(self, i, j):
        """
        Defines which cell borders should be drawn.
        Returns a string containing some or all of the letters L/R/T/B,
        to be passed to `fpdf.FPDF.multi_cell()`.
        Can be overriden to customize this logic
        """
        if self._borders_layout == TableBordersLayout.ALL:
            return 1
        if self._borders_layout == TableBordersLayout.NONE:
            return 0

        is_rightmost_column = j == self.rows[i].column_indices[-1]
        rows_count = len(self.rows)
        border = list("LRTB")
        if self._borders_layout == TableBordersLayout.INTERNAL:
            if i == 0:
                border.remove("T")
            if i == rows_count - 1:
                border.remove("B")
            if j == 0:
                border.remove("L")
            if is_rightmost_column:
                border.remove("R")
        if self._borders_layout == TableBordersLayout.MINIMAL:
            if i == 0 or i > self._num_heading_rows or rows_count == 1:
                border.remove("T")
            if i > self._num_heading_rows - 1:
                border.remove("B")
            if j == 0:
                border.remove("L")
            if is_rightmost_column:
                border.remove("R")
        if self._borders_layout == TableBordersLayout.NO_HORIZONTAL_LINES:
            if i > self._num_heading_rows:
                border.remove("T")
            if i != rows_count - 1:
                border.remove("B")
        if self._borders_layout == TableBordersLayout.HORIZONTAL_LINES:
            if rows_count == 1:
                return 0
            border = list("TB")
            if i == 0 and "T" in border:
                border.remove("T")
            elif i == rows_count - 1:
                border.remove("B")
        if self._borders_layout == TableBordersLayout.SINGLE_TOP_LINE:
            if rows_count == 1:
                return 0
            return "B" if i < self._num_heading_rows else 0
        return "".join(border)

    def _render_table_row(
        self, i, row_layout_info, cell_x_positions, fill=False, **kwargs
    ):
        row = self.rows[i]
        j = 0
        y = self._fpdf.y  # remember current y position, reset after each cell

        for cell in row.cells:
            self._render_table_cell(
                i,
                j,
                cell,
                row_height=self._line_height,
                cell_height_info=row_layout_info,
                cell_x_positions=cell_x_positions,
                fill=fill,
                **kwargs,
            )
            j += cell.colspan
            self._fpdf.set_y(y)  # restore y position after each cell

        self._fpdf.ln(row_layout_info.height)

    def _render_table_cell(
        self,
        i,
        j,
        cell,
        row_height,  # height of a row of text including line spacing
        fill=False,
        cell_height_info=None,  # full height of a cell, including padding, used to render borders and images
        cell_x_positions=None,  # x-positions of the individual columns, pre-calculated for speed. Only relevant when rendering
        **kwargs,
    ):
        # If cell_height_info is provided then we are rendering a cell
        # If cell_height_info is not provided then we are only here to figure out the height of the cell
        #
        # So this function is first called without cell_height_info to figure out the heights of all cells in a row
        # and then called again with cell_height to actually render the cells

        if cell_height_info is None:
            cell_height = None
            height_query_only = True
        else:
            cell_height = cell_height_info.height
            height_query_only = False

        page_break_text = False
        page_break_image = False

        # Get style and cell content:

        row = self.rows[i]
        col_width = self._get_col_width(i, j, cell.colspan)
        img_height = 0

        text_align = cell.align or self._text_align
        if not isinstance(text_align, (Align, str)):
            text_align = text_align[j]
        if i < self._num_heading_rows:
            # Get the style for this cell by overriding the row style with any provided
            # headings style, and overriding that with any provided cell style
            style = FontFace.combine(
                cell.style, FontFace.combine(self._headings_style, row.style)
            )
        else:
            style = FontFace.combine(cell.style, row.style)
        if style and style.fill_color:
            fill = True
        elif (
            not fill
            and self._cell_fill_color
            and self._cell_fill_mode != TableCellFillMode.NONE
        ):
            if self._cell_fill_mode == TableCellFillMode.ALL:
                fill = True
            elif self._cell_fill_mode == TableCellFillMode.ROWS:
                fill = bool(i % 2)
            elif self._cell_fill_mode == TableCellFillMode.COLUMNS:
                fill = bool(j % 2)
        if fill and self._cell_fill_color and not (style and style.fill_color):
            style = (
                style.replace(fill_color=self._cell_fill_color)
                if style
                else FontFace(fill_color=self._cell_fill_color)
            )

        padding = Padding.new(cell.padding) if cell.padding else self._padding

        v_align = cell.v_align if cell.v_align else self._v_align

        # We can not rely on the actual x position of the cell. Notably in case of
        # empty cells or cells with an image only the actual x position is incorrect.
        # Instead, we calculate the x position based on the column widths of the previous columns

        # place cursor (required for images after images)

        if (
            height_query_only
        ):  # not rendering, cell_x_positions is not relevant (and probably not provided)
            cell_x = 0
        else:
            cell_x = cell_x_positions[j]

        self._fpdf.set_x(self._fpdf.l_margin + cell_x)

        # render cell border and background

        # if cell_height is defined, that means that we already know the size at which the cell will be rendered
        # so we can draw the borders now
        #
        # If cell_height is None then we're still in the phase of calculating the height of the cell meaning that
        # we do not need to set fonts & draw borders yet.

        if not height_query_only:
            x1 = self._fpdf.x
            y1 = self._fpdf.y
            x2 = (
                x1 + col_width
            )  # already includes gutter for cells spanning multiple columns
            y2 = y1 + cell_height

            self._borders_layout.cell_style_getter(
                row_num=i,
                col_num=j,
                num_heading_rows=self._num_heading_rows,
                num_rows=len(self.rows),
                num_cols=self.rows[i].column_indices[-1] + 1,
            ).draw_cell_border(
                self._fpdf,
                x1,
                y1,
                x2,
                y2,
                fill_color=style.fill_color if fill else None,
            )

        # render image

        if cell.img:
            x, y = self._fpdf.x, self._fpdf.y

            # if cell_height is None or width is given then call image with h=0
            # calling with h=0 means that the image will be rendered with an auto determined height
            auto_height = cell.img_fill_width or cell_height is None
            cell_border_line_width = self._fpdf.line_width

            # apply padding
            self._fpdf.x += padding.left + cell_border_line_width / 2
            self._fpdf.y += padding.top + cell_border_line_width / 2

            image = self._fpdf.image(
                cell.img,
                w=col_width - padding.left - padding.right - cell_border_line_width,
                h=0
                if auto_height
                else cell_height
                - padding.top
                - padding.bottom
                - cell_border_line_width,
                keep_aspect_ratio=True,
                link=cell.link,
            )

            img_height = (
                image.rendered_height
                + padding.top
                + padding.bottom
                + cell_border_line_width
            )

            if img_height + y > self._fpdf.page_break_trigger:
                page_break_image = True

            self._fpdf.set_xy(x, y)

        # render text

        if cell.text:
            dy = 0

            if cell_height is not None:
                actual_text_height = cell_height_info.rendered_height[j]

                if v_align == VAlign.M:
                    dy = (cell_height - actual_text_height) / 2
                elif v_align == VAlign.B:
                    dy = cell_height - actual_text_height

            self._fpdf.y += dy

            with self._fpdf.use_font_face(style):
                page_break_text, cell_height = self._fpdf.multi_cell(
                    w=col_width,
                    h=row_height,
                    text=cell.text,
                    max_line_height=self._line_height,
                    border=0,
                    align=text_align,
                    new_x="RIGHT",
                    new_y="TOP",
                    fill=False,  # fill is already done above
                    markdown=self._markdown,
                    output=MethodReturnValue.PAGE_BREAK | MethodReturnValue.HEIGHT,
                    wrapmode=self._wrapmode,
                    padding=padding,
                    **kwargs,
                )

            self._fpdf.y -= dy
        else:
            cell_height = 0

        do_pagebreak = page_break_text or page_break_image

        return do_pagebreak, img_height, cell_height

    def _get_col_width(self, i, j, colspan=1):
        """Gets width of a column in a table, this excludes the outer gutter (outside the table) but includes the inner gutter
        between columns if the cell spans multiple columns."""

        cols_count = self.rows[i].cols_count
        width = self._width - (cols_count - 1) * self._gutter_width

        gutter_within_cell = max((colspan - 1) * self._gutter_width, 0)

        if not self._col_widths:
            return colspan * (width / cols_count) + gutter_within_cell
        if isinstance(self._col_widths, Number):
            return colspan * self._col_widths + gutter_within_cell
        if j >= len(self._col_widths):
            raise ValueError(
                f"Invalid .col_widths specified: missing width for table() column {j + 1} on row {i + 1}"
            )
        col_width = 0
        for k in range(j, j + colspan):
            col_ratio = self._col_widths[k] / sum(self._col_widths)
            col_width += col_ratio * width
            if k != j:
                col_width += self._gutter_width
        return col_width

    def _get_row_layout_info(self, i):
        """
        Compute the cells heights & detect page jumps,
        but disable actual rendering by using FPDF._disable_writing()

        Text governs the height of a row, images are scaled accordingly.
        Except if there is no text, then the image height is used.

        """
        row = self.rows[i]
        dictated_heights_per_cell = []
        image_heights_per_cell = []

        rendered_height = {}  # as dict because j is not continuous in case of colspans
        any_page_break = False
        # pylint: disable=protected-access
        with self._fpdf._disable_writing():
            j = 0
            for cell in row.cells:
                page_break, image_height, text_height = self._render_table_cell(
                    i,
                    j,
                    cell,
                    row_height=self._line_height,
                )

                if cell.img_fill_width:
                    dictated_height = image_height
                else:
                    dictated_height = text_height

                # store the rendered height in the cell as info
                # Can not store in the cell as this is a frozen dataclass
                # so store in RowLayoutInfo instead
                rendered_height[j] = max(image_height, dictated_height)

                j += cell.colspan
                any_page_break = any_page_break or page_break

                image_heights_per_cell.append(image_height)
                dictated_heights_per_cell.append(dictated_height)

        # The text governs the row height, but if there is no text, then the image governs the row height
        row_height = (
            max(height for height in dictated_heights_per_cell)
            if dictated_heights_per_cell
            else 0
        )

        if row_height == 0:
            row_height = (
                max(height for height in image_heights_per_cell)
                if image_heights_per_cell
                else 0
            )

        return RowLayoutInfo(row_height, any_page_break, rendered_height)


class Row:
    "Object that `Table.row()` yields, used to build a row in a table"

    def __init__(self, fpdf):
        self._fpdf = fpdf
        self.cells = []
        self.style = fpdf.font_face()

    @property
    def cols_count(self):
        return sum(cell.colspan for cell in self.cells)

    @property
    def column_indices(self):
        columns_count = len(self.cells)
        colidx = 0
        indices = [colidx]
        for jj in range(columns_count - 1):
            colidx += self.cells[jj].colspan
            indices.append(colidx)
        return indices

    def cell(
        self,
        text="",
        align=None,
        v_align=None,
        style=None,
        img=None,
        img_fill_width=False,
        colspan=1,
        padding=None,
        link=None,
    ):
        """
        Adds a cell to the row.

        Args:
            text (str): string content, can contain several lines.
                In that case, the row height will grow proportionally.
            align (str, fpdf.enums.Align): optional text alignment.
            v_align (str, fpdf.enums.AlignV): optional vertical text alignment.
            style (fpdf.fonts.FontFace): optional text style.
            img: optional. Either a string representing a file path to an image,
                an URL to an image, an io.BytesIO, or a instance of `PIL.Image.Image`.
            img_fill_width (bool): optional, defaults to False. Indicates to render the image
                using the full width of the current table column.
            colspan (int): optional number of columns this cell should span.
            padding (tuple): optional padding (left, top, right, bottom) for the cell.
            link (str, int): optional link, either an URL or an integer returned by `FPDF.add_link`, defining an internal link to a page

        """
        if text and img:
            raise NotImplementedError(
                "fpdf2 currently does not support inserting text with an image in the same table cell."
                "Pull Requests are welcome to implement this 😊"
            )
        if not style:
            # We capture the current font settings:
            font_face = self._fpdf.font_face()
            if font_face != self.style:
                style = font_face
        cell = Cell(
            text, align, v_align, style, img, img_fill_width, colspan, padding, link
        )
        self.cells.append(cell)
        return cell


@dataclass(frozen=True)
class Cell:
    "Internal representation of a table cell"
    __slots__ = (  # RAM usage optimization
        "text",
        "align",
        "v_align",
        "style",
        "img",
        "img_fill_width",
        "colspan",
        "padding",
        "link",
    )
    text: str
    align: Optional[Union[str, Align]]
    v_align: Optional[Union[str, VAlign]]
    style: Optional[FontFace]
    img: Optional[str]
    img_fill_width: bool
    colspan: int
    padding: Optional[Union[int, tuple, type(None)]]
    link: Optional[Union[str, int]]

    def write(self, text, align=None):
        raise NotImplementedError("Not implemented yet")
