from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Preformatted
from reportlab.lib.enums import TA_LEFT

OUTPUT = "SuperDial_API_Design_Documentation.pdf"

doc = SimpleDocTemplate(
    OUTPUT,
    pagesize=letter,
    rightMargin=inch,
    leftMargin=inch,
    topMargin=inch,
    bottomMargin=inch,
)

styles = getSampleStyleSheet()

label = ParagraphStyle(
    "label",
    parent=styles["Normal"],
    fontName="Helvetica-Bold",
    fontSize=11,
    spaceAfter=4,
)

body = ParagraphStyle(
    "body",
    parent=styles["Normal"],
    fontName="Helvetica",
    fontSize=11,
    spaceAfter=12,
    leading=16,
)

code = ParagraphStyle(
    "code",
    parent=styles["Normal"],
    fontName="Courier",
    fontSize=9,
    spaceAfter=12,
    leading=14,
    backColor=colors.HexColor("#f5f5f5"),
    leftIndent=12,
    rightIndent=12,
)

note = ParagraphStyle(
    "note",
    parent=styles["Normal"],
    fontName="Helvetica-Oblique",
    fontSize=10,
    textColor=colors.red,
    spaceAfter=16,
)

content = []

content.append(Paragraph(
    "Note: This tool is not externally accessible. It runs locally on a company machine with no public-facing UI.",
    note
))

content.append(Paragraph("Company Name:", label))
content.append(Paragraph("SuperDial", body))

content.append(Paragraph("Business Model:", label))
content.append(Paragraph(
    "SuperDial is a B2B SaaS company that automates payer-provider communications for healthcare revenue cycle "
    "teams using AI voice agents. We run paid search campaigns on Google Ads targeting healthcare billing and RCM "
    "decision-makers to drive demo bookings. We advertise only for superdial.com, which we own, and do not manage "
    "ads for any other company.",
    body
))

content.append(Paragraph("Tool Access/Use:", label))
content.append(Paragraph(
    "This tool is an internal Python script used exclusively by SuperDial's marketing team (1–2 employees) to "
    "support our content and SEO strategy. It is not externally accessible, has no public-facing UI, and will not "
    "be shared with or accessed by any third parties. The tool runs locally on a company machine and outputs a CSV "
    "file for internal review.",
    body
))

content.append(Paragraph("Tool Design:", label))
content.append(Paragraph(
    "The tool calls the Google Ads Keyword Planner API using a seed list of industry-relevant keywords. It "
    "retrieves keyword ideas along with average monthly search volume, competition level, and CPC range. Results "
    "are sorted by search volume and saved to a local CSV file. The marketing team reviews the CSV to identify "
    "high-value topics, then manually selects keywords to inform blog and content production. No data is stored "
    "in an external database or transmitted to any outside system.",
    body
))

content.append(Paragraph("API Services Called:", label))
content.append(Paragraph(
    "&#8226; Pull keyword ideas and search volume data using the <b>KeywordPlanIdeaService</b> "
    "(GenerateKeywordIdeas method)",
    body
))

content.append(Paragraph("Tool Mockups:", label))
content.append(Paragraph("Terminal output sample:", body))

terminal_output = """\
Pulling keyword ideas for 10 seed keywords...
Done. 312 keywords saved to keywords.csv

Top 20 by search volume:
Keyword                                   Searches  Competition     CPC Range
------------------------------------------------------------------------------
eligibility verification software           18,100         HIGH  $12.40-$38.20
prior authorization automation              12,400         HIGH  $14.10-$41.50
revenue cycle automation                     9,900       MEDIUM   $9.80-$28.60
healthcare voice AI                          5,400       MEDIUM  $11.20-$33.40
payer call automation                        2,900         HIGH  $13.50-$39.00"""

content.append(Preformatted(terminal_output, code))

content.append(Paragraph("CSV output sample:", body))

csv_output = """\
keyword,avg_monthly_searches,competition,low_cpc,high_cpc
eligibility verification software,18100,HIGH,12.40,38.20
prior authorization automation,12400,HIGH,14.10,41.50
revenue cycle automation,9900,MEDIUM,9.80,28.60
healthcare voice AI,5400,MEDIUM,11.20,33.40
payer call automation,2900,HIGH,13.50,39.00"""

content.append(Preformatted(csv_output, code))

doc.build(content)
print(f"Saved to {OUTPUT}")
