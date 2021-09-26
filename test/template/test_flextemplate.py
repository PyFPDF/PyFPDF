from pathlib import Path
from fpdf.fpdf import FPDF
from fpdf.template import FlexTemplate
from ..conftest import assert_pdf_equal

HERE = Path(__file__).resolve().parent


def test_flextemplate_offset(tmp_path):
    elements = [
        {
            "name": "box",
            "type": "B",
            "x1": 0,
            "y1": 0,
            "x2": 50,
            "y2": 50,
        },
        {
            "name": "d1",
            "type": "L",
            "x1": 0,
            "y1": 0,
            "x2": 50,
            "y2": 50,
        },
        {
            "name": "d2",
            "type": "L",
            "x1": 0,
            "y1": 50,
            "x2": 50,
            "y2": 0,
        },
        {
            "name": "label",
            "type": "T",
            "x1": 0,
            "y1": 52,
            "x2": 50,
            "y2": 57,
            "text": "Label",
        },
    ]
    pdf = FPDF()
    pdf.add_page()
    templ = FlexTemplate(pdf, elements)
    templ["label"] = "Offset: 50 / 50 mm"
    templ.render(offsetx=50, offsety=50)
    templ["label"] = "Offset: 50 / 120 mm"
    templ.render(offsetx=50, offsety=120)
    templ["label"] = "Offset: 120 / 50 mm"
    templ.render(offsetx=120, offsety=50)
    templ["label"] = "Offset: 120 / 120 mm, Rotate: 30°"
    templ.render(offsetx=120, offsety=120, rotate=30.0)
    assert_pdf_equal(pdf, HERE / "flextemplate_offset.pdf", tmp_path)


def test_flextemplate_multipage(tmp_path):

    elements = [
            {"name":"box", "type":"B", "x1":0, "y1":0, "x2":50, "y2":50,},
            {"name":"d1", "type":"L", "x1":0, "y1":0, "x2":50, "y2":50,},
            {"name":"d2", "type":"L", "x1":0, "y1":50, "x2":50, "y2":0,},
            {"name":"label", "type":"T", "x1":0, "y1":52, "x2":50, "y2":57, "text":"Label",},
            ]
    pdf = FPDF()
    pdf.add_page()
    tmpl_0 = FlexTemplate(pdf, elements)
    tmpl_0["label"] = "Offset: 50 / 50 mm"
    tmpl_0.render(offsetx=50, offsety=50)
    tmpl_0["label"] = "Offset: 50 / 120 mm"
    tmpl_0.render(offsetx=50, offsety=120)
    tmpl_0["label"] = "Offset: 120 / 50 mm"
    tmpl_0.render(offsetx=120, offsety=50)
    tmpl_0["label"] = "Offset: 120 / 120 mm"
    tmpl_0.render(offsetx=120, offsety=120, rotate=30.0)
    pdf.add_page()
    tmpl_0["label"] = "Offset: 120 / 50 mm"
    tmpl_0.render(offsetx=120, offsety=50)
    tmpl_0["label"] = "Offset: 120 / 120 mm"
    tmpl_0.render(offsetx=120, offsety=120, rotate=30.0)
    tmpl_1 = FlexTemplate(pdf)
    tmpl_1.parse_csv(HERE / "mycsvfile.csv", delimiter=";")
    tmpl_1.render()
    assert_pdf_equal(pdf, HERE / "flextemplate_multipage.pdf", tmp_path)
