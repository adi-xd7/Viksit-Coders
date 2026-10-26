// Builds ../Ragnarok_Agentic_AI_Pitch.pptx (16:9, editable, speaker notes included).
// Run from this folder:  npm install  &&  node build_deck.js
// Raster assets come from ../assets (made by make_assets.py: procedural backgrounds and
// emblems, plus crops of real dashboard captures). Every figure on the slides is taken from
// the saved two-run case logs/demo/case-20261026-005913-e4e654 or from the README.

const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require("./apply_theme.js");

const A = (f) => path.join(__dirname, "..", "assets", f);
const OUT = path.join(__dirname, "..", "Ragnarok_Agentic_AI_Pitch.pptx");
const CASE = "case-20261026-005913-e4e654";

const THEME = {
  name: "Ragnarok",
  headFontFace: "Garamond",
  bodyFontFace: "Inter",
  colors: {
    dk1: "090B10", // obsidian
    lt1: "E8E5DC", // cold ivory
    dk2: "141821", // deep charcoal
    lt2: "9299A6", // muted silver
    accent1: "76B9FF", // ice blue: evidence and system flow
    accent2: "C5A66A", // antique gold: Odin's judgment
    accent3: "B84B54", // muted crimson: disputes, warnings
    accent4: "1A1F2A", // panel
    accent5: "2E3646", // hairline
    accent6: "4F6E93", // deep ice
    hlink: "76B9FF",
    folHlink: "C5A66A",
  },
};

const pres = new pptxgen();
pres.layout = "LAYOUT_WIDE"; // 13.333 x 7.5 in
pres.title = "Ragnarok: Trial of the Nine Realms";
pres.subject = "Agentic AI pitch deck";
pres.author = "Team Viksit Coders";
pres.company = "Viksit Coders";
pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };

const C = pres.SchemeColor;
const OBS = C.text1, IVORY = C.background1, CHAR = C.text2, SILVER = C.background2;
const ICE = C.accent1, GOLD = C.accent2, CRIM = C.accent3, PANEL = C.accent4, LINE = C.accent5, ICED = C.accent6;
const MONO = "Consolas";
const S = pres.shapes;

const W = 13.333, M = 0.6, CW = W - 2 * M; // content width 12.133

// ------------------------------------------------------------------ layouts
const footer = [
  { text: { text: "RAGNAROK  ·  TRIAL OF THE NINE REALMS", options: { x: M, y: 7.0, w: 6, h: 0.25, fontFace: MONO, fontSize: 9, color: SILVER, charSpacing: 2, margin: 0, isTextBox: true } } },
];
pres.defineSlideMaster({
  title: "CONTENT",
  background: { path: A("bg_content.jpg") },
  objects: [
    { placeholder: { options: { name: "eyebrow", type: "body", x: M, y: 0.42, w: 8, h: 0.28, fontFace: MONO, fontSize: 11, color: ICE, charSpacing: 3, margin: 0, valign: "top" }, text: "" } },
    { placeholder: { options: { name: "title", type: "title", x: M, y: 0.72, w: CW, h: 0.9, fontFace: "Garamond", fontSize: 32, color: IVORY, margin: 0, valign: "top", align: "left", bold: false }, text: "" } },
    ...footer,
  ],
  slideNumber: { x: W - M - 0.5, y: 7.0, w: 0.5, h: 0.25, fontFace: MONO, fontSize: 9, color: SILVER, align: "right" },
});
pres.defineSlideMaster({ title: "COVER", background: { path: A("bg_open.jpg") }, objects: [] });
pres.defineSlideMaster({ title: "CLOSE", background: { path: A("bg_close.jpg") }, objects: [] });

// ------------------------------------------------------------------ helpers
function T(slide, text, o) {
  slide.addText(text, Object.assign({ isTextBox: true, margin: 0, fontSize: 14, color: IVORY, valign: "top", paraSpaceAfter: 0 }, o));
}
function box(slide, x, y, w, h, o = {}) {
  slide.addShape(S.RECTANGLE, Object.assign({ x, y, w, h, fill: { color: PANEL }, line: { color: LINE, width: 0.75 } }, o));
}
function line(slide, x1, y1, x2, y2, o = {}) {
  const x = Math.min(x1, x2), y = Math.min(y1, y2), w = Math.abs(x2 - x1), h = Math.abs(y2 - y1);
  const flipH = x2 < x1, flipV = y2 < y1;
  slide.addShape(S.LINE, Object.assign({ x, y, w: w || 0.0001, h: h || 0.0001, flipH, flipV, line: { color: SILVER, width: 1 } }, o));
}
function arrow(slide, x1, y1, x2, y2, color = SILVER, o = {}) {
  line(slide, x1, y1, x2, y2, { line: Object.assign({ color, width: 1.25, endArrowType: "triangle" }, o) });
}
function chip(slide, x, y, text, color = ICE, w) {
  const width = w || 0.12 + text.length * 0.085;
  slide.addShape(S.RECTANGLE, { x, y, w: width, h: 0.28, fill: { color: OBS, transparency: 30 }, line: { color, width: 0.75 } });
  T(slide, text, { x, y, w: width, h: 0.28, fontFace: MONO, fontSize: 10, color, align: "center", valign: "middle" });
  return width;
}
function eyebrowTitle(slide, eyebrow, title) {
  slide.addText(eyebrow, { placeholder: "eyebrow" });
  slide.addText(title, { placeholder: "title" });
}
function content(section) {
  return pres.addSlide({ masterName: "CONTENT", sectionTitle: section });
}
// verdict glyphs, as on the dashboard: filled, half, hollow, red square
function glyph(slide, kind, x, y, d = 0.2) {
  if (kind === "established") slide.addShape(S.OVAL, { x, y, w: d, h: d, fill: { color: IVORY }, line: { color: IVORY, width: 1 } });
  if (kind === "contested") {
    slide.addShape(S.PIE, { x, y, w: d, h: d, angleRange: [90, 270], fill: { color: IVORY }, line: { color: IVORY, width: 0 } });
    slide.addShape(S.OVAL, { x, y, w: d, h: d, fill: { color: IVORY, transparency: 100 }, line: { color: IVORY, width: 1.25 } });
  }
  if (kind === "conceded") slide.addShape(S.OVAL, { x, y, w: d, h: d, fill: { color: IVORY, transparency: 100 }, line: { color: SILVER, width: 1.25 } });
  if (kind === "rejected") slide.addShape(S.RECTANGLE, { x, y, w: d, h: d, fill: { color: CRIM }, line: { color: CRIM, width: 1 } });
}

// ================================================================== 1. Opening
pres.addSection({ title: "Opening" });
{
  const s = pres.addSlide({ masterName: "COVER", sectionTitle: "Opening" });
  T(s, "RAGNAROK", { x: 0.5, y: 1.55, w: W - 1, h: 1.5, fontFace: "Garamond", fontSize: 96, color: IVORY, align: "center", valign: "middle", charSpacing: 18 });
  T(s, "TRIAL OF THE NINE REALMS", { x: 0.5, y: 3.05, w: W - 1, h: 0.4, fontSize: 15, color: ICE, align: "center", charSpacing: 9 });
  T(s, "An agentic intelligence system for investigating supply-chain disruption", { x: 1.5, y: 3.6, w: W - 3, h: 0.5, fontFace: "Garamond", italic: true, fontSize: 22, color: IVORY, align: "center" });
  T(s, "AGENTIC AI HACKATHON  ·  RAGNAROK", { x: M, y: 6.85, w: 6, h: 0.3, fontFace: MONO, fontSize: 10, color: SILVER, charSpacing: 2 });
  T(s, "TEAM VIKSIT CODERS", { x: W - M - 6, y: 6.85, w: 6, h: 0.3, fontFace: MONO, fontSize: 10, color: SILVER, align: "right", charSpacing: 2 });
  s.addNotes(
`KEY POINT: Introduce Ragnarok in one breath: a multi-agent system that investigates a supply-chain disruption and earns its conclusion.

SCRIPT: Good morning. We are Team Viksit Coders, and this is Ragnarok: Trial of the Nine Realms. When a trade corridor shuts down, someone has to answer a hard question quickly: who is exposed, and by how much? We built a system that answers it the way a careful investigation would, with research, competing arguments, cross-examination and a judge who rules from the evidence.

TRANSITION: Let me start with why that question is hard.

IF ASKED: The names come from Norse mythology, but each one is a concrete role in the code: an investigator, two opposing advocates and a judge.`);
}

// ================================================================== 2. Problem
pres.addSection({ title: "Problem" });
{
  const s = content("Problem");
  eyebrowTitle(s, "THE PROBLEM", "A disrupted corridor can become a national risk\nbefore the picture is clear");
  // evidence landscape (left)
  const nx = (x, y, w, label, sub, col) => {
    box(s, x, y, w, 0.62, { line: { color: col, width: 1 } });
    T(s, label, { x: x + 0.15, y: y + 0.08, w: w - 0.3, h: 0.28, fontSize: 14, bold: true, color: IVORY });
    T(s, sub, { x: x + 0.15, y: y + 0.35, w: w - 0.3, h: 0.22, fontSize: 10, color: SILVER });
  };
  nx(0.8, 3.75, 1.75, "Exporter", "grain by sea", SILVER);
  nx(5.15, 2.45, 1.9, "Importer A", "wheat, maize", IVORY);
  nx(5.15, 5.05, 1.9, "Importer B", "wheat, maize", IVORY);
  // disrupted corridor
  line(s, 2.55, 4.06, 5.15, 2.76, { line: { color: CRIM, width: 2, dashType: "dash" } });
  line(s, 2.55, 4.06, 5.15, 5.36, { line: { color: CRIM, width: 2, dashType: "dash" } });
  T(s, "×", { x: 3.62, y: 3.08, w: 0.4, h: 0.4, fontSize: 24, color: CRIM, align: "center", valign: "middle" });
  T(s, "×", { x: 3.62, y: 4.42, w: 0.4, h: 0.4, fontSize: 24, color: CRIM, align: "center", valign: "middle" });
  T(s, "corridor agreement ends", { x: 1.6, y: 4.95, w: 2.6, h: 0.25, fontFace: MONO, fontSize: 10, color: CRIM });
  // alternative routes, unknown capacity
  nx(2.55, 5.8, 1.75, "Alternatives?", "other suppliers, rail", SILVER);
  line(s, 4.3, 6.11, 5.15, 5.6, { line: { color: SILVER, width: 1, dashType: "sysDot" } });
  // evidence fragments
  const frag = [
    [0.8, 2.2, "official notice · T1"], [2.7, 2.35, "correction"], [0.8, 2.75, "rumour · T4"],
    [7.35, 3.55, "trade table"], [7.35, 3.95, "report after as-of"], [7.35, 4.35, "conflicting report"],
  ];
  frag.forEach(([x, y, t]) => chip(s, x, y, t, ICE));
  line(s, 2.2, 2.48, 3.3, 3.45, { line: { color: ICED, width: 0.75 } });
  line(s, 7.35, 3.69, 7.05, 2.9, { line: { color: ICED, width: 0.75 } });
  line(s, 7.35, 4.49, 7.05, 5.2, { line: { color: ICED, width: 0.75 } });
  // questions (right)
  const qx = 9.35;
  T(s, "QUESTIONS THAT ARRIVE AT ONCE", { x: qx, y: 2.05, w: 3.4, h: 0.25, fontFace: MONO, fontSize: 10, color: SILVER, charSpacing: 2 });
  const qs = ["Which countries and sectors are exposed?", "How much trade is actually at risk?", "Can other routes, suppliers or stocks cover it?", "Which claims rest on reliable evidence?", "What is still missing?"];
  qs.forEach((q, i) => {
    s.addImage({ path: A("stave_ice.png"), x: qx, y: 2.47 + i * 0.66, w: 0.1, h: 0.2 });
    T(s, q, { x: qx + 0.25, y: 2.42 + i * 0.66, w: 3.15, h: 0.55, fontSize: 14, color: IVORY });
  });
  T(s, "The hard part is not finding information. It is reconciling it into a defensible assessment.", { x: qx, y: 5.85, w: 3.4, h: 0.85, fontFace: "Garamond", italic: true, fontSize: 18, color: IVORY });
  T(s, "Illustration. Roles taken from the Runemark dev pack (fictional).", { x: M, y: 6.72, w: 6, h: 0.22, fontSize: 10, color: SILVER });
  s.addNotes(
`KEY POINT: The difficulty is reconciling scattered, conflicting evidence, not finding it.

SCRIPT: Picture an export corridor for grain whose agreement simply ends. Two importing countries depend on it. Within days the questions pile up: who is exposed, how much trade is at risk, can other suppliers or a rail link cover the gap, and which of the claims flying around are actually reliable? The evidence is spread across official notices, trade tables, corrections of earlier reports, rumours, and even reports dated after the moment you are asking about. Finding documents is easy. Turning them into a defensible assessment is the hard part.

TRANSITION: So why not just ask a single model?

IF ASKED: The challenge dataset, Runemark, is fictional but deliberately messy: an empty file, a cut-off copy, a UTF-16 body, documents after the as-of date, a retracted renewal report, tier-4 rumours and an embedded instruction aimed at the AI.`);
}

// ================================================================== 3. Insight
{
  const s = content("Problem");
  eyebrowTitle(s, "THE INSIGHT", "One answer can hide an entire side of the story");
  // single opaque answer
  box(s, M, 2.0, 3.7, 3.9, { fill: { color: CHAR } });
  T(s, "ONE ANSWER", { x: M + 0.3, y: 2.25, w: 3, h: 0.25, fontFace: MONO, fontSize: 10, color: SILVER, charSpacing: 2 });
  [3.1, 2.8, 3.05, 2.4, 2.9, 1.9].forEach((w, i) => s.addShape(S.RECTANGLE, { x: M + 0.3, y: 2.75 + i * 0.32, w, h: 0.1, fill: { color: LINE }, line: { color: LINE, width: 0 } }));
  const risks = ["Incomplete evidence", "One-sided interpretation", "Numbers no one can check"];
  risks.forEach((r, i) => {
    s.addShape(S.RECTANGLE, { x: M + 0.3, y: 4.82 + i * 0.36, w: 0.12, h: 0.12, fill: { color: CRIM }, line: { color: CRIM, width: 0 } });
    T(s, r, { x: M + 0.55, y: 4.73 + i * 0.36, w: 3, h: 0.3, fontSize: 14, color: IVORY });
  });
  arrow(s, 4.55, 3.95, 5.35, 3.95, SILVER);
  // structured investigation
  const st = [
    ["RESEARCH", "Heimdall builds the case file and names what is missing", ICE],
    ["CHALLENGE", "Thor and Loki argue opposite sides and attack each other's claims", IVORY],
    ["VERIFY", "Code checks citations and does every calculation", ICE],
    ["JUDGE", "Odin rules on each claim and decides if more research is needed", GOLD],
  ];
  st.forEach(([k, d, col], i) => {
    const y = 2.0 + i * 1.0;
    box(s, 5.6, y, 7.13, 0.82, { line: { color: i === 3 ? GOLD : LINE, width: i === 3 ? 1.25 : 0.75 } });
    s.addImage({ path: A(col === GOLD ? "stave_gold.png" : "stave_ice.png"), x: 5.85, y: y + 0.21, w: 0.2, h: 0.4 });
    T(s, k, { x: 6.3, y: y + 0.12, w: 2.2, h: 0.6, fontFace: "Garamond", fontSize: 20, color: col, valign: "middle", charSpacing: 2 });
    T(s, d, { x: 8.6, y: y + 0.12, w: 3.95, h: 0.6, fontSize: 14, color: IVORY, valign: "middle" });
  });
  T(s, "A single answer can be right. Separating the stages makes disagreement and evidence gaps visible instead of hidden.", { x: 5.6, y: 6.15, w: 7.13, h: 0.55, fontSize: 13, color: SILVER });
  s.addNotes(
`KEY POINT: Our design principle is Research, Challenge, Verify, Judge, each as a separate stage.

SCRIPT: A single model answer is one voice. It can be right, but you cannot see what it left out, which side of the argument it never considered, or whether its numbers add up. So Ragnarok splits the job. One agent researches. Two agents argue opposite sides and attack each other. Code, not the model, checks every citation and does every calculation. And a judge rules claim by claim, and can send the case back when something essential is missing.

TRANSITION: Here are the four agents that do this.

IF ASKED: We do not claim single-agent systems always fail. The point is visibility: every disagreement and every gap ends up in the record.`);
}

// ================================================================== 4. Agents
pres.addSection({ title: "System" });
{
  const s = content("System");
  eyebrowTitle(s, "THE SYSTEM", "Meet the four agents behind the investigation");
  const ag = [
    ["HEIMDALL", "THE INVESTIGATOR", ICE, "em_heimdall.png", ["Searches documents and trade tables", "Verifies the event, builds the case file", "Flags corrections, rumours and gaps", "Runs targeted research on a send-back"]],
    ["THOR", "HIGH EXPOSURE", IVORY, "em_thor.png", ["Argues exposure is high", "Cited claims, high estimate", "Makes the case for severity"]],
    ["LOKI", "LIMITED EXPOSURE", SILVER, "em_loki.png", ["Argues independently for limited exposure", "Substitutes, other routes, stocks", "Challenges overstated claims"]],
    ["ODIN", "THE JUDGE", GOLD, "em_odin.png", ["Rules on every claim", "Builds his own range from evidence", "Decides if more research is needed", "Writes the briefing from his rulings"]],
  ];
  const cw = 2.78, gap = (CW - 4 * cw) / 3;
  // order line through the emblems
  line(s, M + cw / 2 + 0.7, 2.62, M + 3 * (cw + gap) + cw / 2 - 0.7, 2.62, { line: { color: LINE, width: 1, dashType: "dash" } });
  ag.forEach(([n, role, col, em, pts], i) => {
    const x = M + i * (cw + gap);
    s.addImage({ path: A(em), x: x + cw / 2 - 0.62, y: 2.0, w: 1.24, h: 1.24 });
    T(s, n, { x, y: 3.32, w: cw, h: 0.5, fontFace: "Garamond", fontSize: 26, color: col, align: "center", charSpacing: 4 });
    T(s, role, { x, y: 3.8, w: cw, h: 0.25, fontFace: MONO, fontSize: 10, color: SILVER, align: "center", charSpacing: 2 });
    T(s, pts.map((p, j) => ({ text: p, options: { bullet: { indent: 14 }, breakLine: j < pts.length - 1 } })), { x: x + 0.1, y: 4.22, w: cw - 0.2, h: 2.2, fontSize: 14, color: IVORY, paraSpaceAfter: 6 });
  });
  T(s, "Heimdall opens every case. Odin has the last word. Thor and Loki see each other's claims only at cross-examination.", { x: M, y: 6.66, w: CW, h: 0.28, fontSize: 12, color: SILVER });
  s.addNotes(
`KEY POINT: Four agents, four distinct jobs; each name maps to a concrete role and tool set.

SCRIPT: Heimdall, the watchman, investigates first: he searches the documents and trade tables, checks that the event really happened, notes corrections and rumours, and lists missing data in a case file. Thor argues that exposure is high. Loki, independently, argues that it is limited: substitutes, other routes, stocks. Neither is a villain; they are two analytical perspectives, and each must cite evidence. Odin is the judge. He rules on every claim, builds his own range from the evidence, decides whether more research is needed, and writes the final briefing only from his rulings.

TRANSITION: The important part is how they work together.

IF ASKED: Tool permissions are enforced in code. Heimdall, Thor and Loki can search; Odin cannot search at all. He can read documents, replay calculations and validate citations.`);
}

// ================================================================== 5. Workflow
{
  const s = content("System");
  eyebrowTitle(s, "THE WORKFLOW", "Not four chatbots. One orchestrated investigation.");
  const xs = [0.6, 2.7, 4.8, 6.9, 9.0, 11.13], nw = 1.6, cy = 3.3;
  const node = (x, y, h, title, sub, col, lw = 1) => {
    box(s, x, y, nw, h, { line: { color: col, width: lw } });
    T(s, title, { x: x + 0.12, y: y + 0.12, w: nw - 0.24, h: 0.3, fontSize: 14, bold: true, color: col === LINE ? IVORY : col });
    T(s, sub, { x: x + 0.12, y: y + 0.44, w: nw - 0.24, h: h - 0.5, fontSize: 11, color: SILVER });
  };
  node(xs[0], cy - 0.55, 1.1, "Question", "and as-of date, from the user", LINE);
  node(xs[1], cy - 0.55, 1.1, "Heimdall", "research, case file, event check", ICE, 1.25);
  node(xs[2], cy - 1.35, 1.0, "Thor", "claims, high estimate", IVORY);
  node(xs[2], cy + 0.35, 1.0, "Loki", "claims, low estimate", SILVER);
  node(xs[3], cy - 0.55, 1.1, "Cross-exam", "attack; defend with new evidence or concede", CRIM, 1.25);
  node(xs[4], cy - 0.55, 1.1, "Odin", "rulings, own range, sufficiency", GOLD, 1.5);
  node(xs[5], cy - 0.55, 1.1, "Briefing", "from rulings only", LINE);
  T(s, "in parallel", { x: xs[2], y: cy - 0.32, w: nw, h: 0.25, fontFace: MONO, fontSize: 10, color: SILVER, align: "center" });
  arrow(s, xs[0] + nw, cy, xs[1], cy);
  arrow(s, xs[1] + nw, cy - 0.1, xs[2], cy - 0.85);
  arrow(s, xs[1] + nw, cy + 0.1, xs[2], cy + 0.85);
  arrow(s, xs[2] + nw, cy - 0.85, xs[3], cy - 0.1);
  arrow(s, xs[2] + nw, cy + 0.85, xs[3], cy + 0.1);
  arrow(s, xs[3] + nw, cy, xs[4], cy);
  arrow(s, xs[4] + nw, cy, xs[5], cy, GOLD);
  // send-back loop
  const ly = 5.0, ox = xs[4] + nw / 2, hx = xs[1] + nw / 2;
  line(s, ox, cy + 0.55, ox, ly, { line: { color: GOLD, width: 1.5 } });
  line(s, hx, ly, ox, ly, { line: { color: GOLD, width: 1.5 } });
  arrow(s, hx, ly, hx, cy + 0.55, GOLD, { width: 1.5 });
  T(s, "SEND-BACK  ·  evidence missing → new targeted searches → run 2", { x: hx + 0.2, y: ly + 0.1, w: ox - hx - 0.4, h: 0.28, fontFace: MONO, fontSize: 10, color: GOLD, align: "center" });
  // annotations
  const ann = [
    ["FLOW IN CODE", "An explicit state machine checks every transition. Agent output never picks the next step."],
    ["SHARED CASE FILE", "Every agent works from Heimdall's case file and cites the same stable paragraph and row refs."],
    ["RECORDED DEBATE", "Claims, attacks, defenses, concessions and rulings are append-only audit events."],
    ["BOUNDED LOOP", "Repeated queries are refused; only new evidence counts. Runs are capped at 2 by default."],
  ];
  const aw = (CW - 3 * 0.3) / 4;
  ann.forEach(([k, d], i) => {
    const x = M + i * (aw + 0.3);
    T(s, k, { x, y: 5.75, w: aw, h: 0.25, fontFace: MONO, fontSize: 10, color: ICE, charSpacing: 2 });
    T(s, d, { x, y: 6.03, w: aw, h: 0.8, fontSize: 12, color: IVORY });
  });
  s.addNotes(
`KEY POINT: The workflow is fixed in code, with one conditional loop that Odin can trigger.

SCRIPT: Here is the whole investigation. The user asks a question with an as-of date. Heimdall researches and builds the case file. Thor and Loki then work in parallel, each running their own searches. Cross-examination follows: each side attacks the other's claims, and each attacked claim must be defended with new evidence or conceded. Odin then rules on every claim. If the evidence is sufficient, he writes the briefing. If something essential is missing, he sends the case back: Heimdall runs new targeted searches, and the trial runs again with whatever new evidence turns up.

TRANSITION: Let us zoom into what happens to a single claim.

IF ASKED: There is no central planner. The state machine is USER, HEIMDALL, THOR and LOKI, CROSS_EXAMINATION, ODIN, then BRIEFING or HEIMDALL_RESEARCH. Odin names the missing evidence but never assigns tasks. Run 2 refuses repeated queries and excludes paragraphs already seen.`);
}

// ================================================================== 6. Reasoning
pres.addSection({ title: "Proof" });
{
  const s = content("Proof");
  eyebrowTitle(s, "HOW THE SYSTEM REASONS", "Every claim must survive scrutiny");
  const cw = 2.83, gap = (CW - 4 * cw) / 3, y0 = 1.95, ch = 3.0;
  const cards = [
    ["CLAIM", "Loki  ·  L1-2  ·  inference", SILVER, "Midgard's maize imports from Orvan stayed more resilient after the agreement ended, thanks to delayed delivery terms.", ["ORV-0030 P14", "ORV-0030 R4"]],
    ["ATTACK", "Thor  ·  A1-T3", CRIM, "\"Resilient\" describes a delay. November value fell from USD 84.7M (2025) to 31.9M (2026).", ["ORV-0030 R11", "ORV-0030 R5"]],
    ["RESPONSE", "Loki  ·  concedes in part", SILVER, "\"Resilient\" inaccurately describes the maize trade. The claim is revised to a delayed but significant decline.", []],
    ["RULING", "Odin  ·  R-L1-2", GOLD, "Conceded. The proponent acknowledged the objection; the trade suffered heavy year-on-year losses.", []],
  ];
  cards.forEach(([k, who, col, txt, cites], i) => {
    const x = M + i * (cw + gap);
    box(s, x, y0, cw, ch, { line: { color: i === 3 ? GOLD : LINE, width: i === 3 ? 1.25 : 0.75 } });
    T(s, k, { x: x + 0.2, y: y0 + 0.18, w: cw - 0.4, h: 0.25, fontFace: MONO, fontSize: 10, color: col === SILVER ? ICE : col, charSpacing: 2 });
    T(s, who, { x: x + 0.2, y: y0 + 0.45, w: cw - 0.4, h: 0.25, fontSize: 11, color: SILVER });
    T(s, txt, { x: x + 0.2, y: y0 + 0.82, w: cw - 0.4, h: 1.6, fontSize: 14, color: IVORY });
    cites.forEach((c, j) => chip(s, x + 0.2 + j * 1.27, y0 + ch - 0.48, c, ICE, 1.17));
    if (i === 3) glyph(s, "conceded", x + cw - 0.45, y0 + 0.2);
    if (i < 3) arrow(s, x + cw + 0.04, y0 + ch / 2, x + cw + gap - 0.04, y0 + ch / 2, SILVER);
  });
  // verdicts
  const vy = 5.3;
  T(s, "FOUR VERDICTS, USED EVERYWHERE", { x: M, y: vy, w: 6, h: 0.25, fontFace: MONO, fontSize: 10, color: SILVER, charSpacing: 2 });
  const vs = [["established", "survived scrutiny on valid evidence"], ["contested", "support, but credible counter-evidence"], ["conceded", "the claim's author withdrew it"], ["rejected", "Odin judged it unsupported"]];
  const vw = CW / 4;
  vs.forEach(([v, d], i) => {
    const x = M + i * vw;
    glyph(s, v, x, vy + 0.42);
    T(s, v, { x: x + 0.32, y: vy + 0.36, w: vw - 0.4, h: 0.3, fontSize: 14, bold: true, color: v === "rejected" ? CRIM : IVORY });
    T(s, d, { x: x + 0.32, y: vy + 0.68, w: vw - 0.45, h: 0.5, fontSize: 12, color: SILVER });
  });
  T(s, `Conceded comes from the author; rejected from Odin. Every claim is tagged fact or inference. Real exchange from the saved case, condensed.`, { x: M, y: 6.6, w: CW, h: 0.28, fontSize: 11, color: SILVER });
  s.addNotes(
`KEY POINT: A claim only stands if it survives attack, and the four verdicts mean different things.

SCRIPT: This is a real exchange from our saved two-run case. Loki claimed that Midgard's maize imports stayed resilient after the agreement ended, citing a trade note. Thor attacked with two trade rows: November value fell from 84.7 to 31.9 million dollars year on year. Loki could defend only with new evidence, and had none, so he conceded in part. Odin then recorded the claim as conceded. There are four verdicts. Established means it survived scrutiny. Contested means credible counter-evidence remains. Conceded means the author backed down. Rejected means Odin judged it unsupported. Conceded and rejected are deliberately different.

TRANSITION: Claims often carry numbers. Here is how we make those numbers trustworthy.

IF ASKED: The code refuses generic attacks: an attack needs a target claim, a specific objection, and counter-evidence or a named gap. A defense that cites nothing new is recorded as invalid, and the claim stays undefended for Odin. "Conceded" is only possible if the author actually conceded.`);
}

// ================================================================== 7. Numbers
{
  const s = content("Proof");
  eyebrowTitle(s, "NUMBERS YOU CAN TRACE", "The model reasons. Code does the arithmetic.");
  const y = 2.05, h = 2.75;
  const col = [
    [M, 1.9, "SOURCE DOCUMENT", ICE],
    [2.8, 1.9, "CITED TRADE ROWS", ICE],
    [5.0, 3.7, "DETERMINISTIC CALCULATION", ICE],
    [9.0, 2.05, "EXPOSURE RANGE", GOLD],
    [11.35, 1.38, "BRIEFING", IVORY],
  ];
  col.forEach(([x, w, k, c], i) => {
    box(s, x, y, w, h, { line: { color: i === 2 ? ICE : i === 3 ? GOLD : LINE, width: i === 2 || i === 3 ? 1.25 : 0.75 } });
    T(s, k, { x: x + 0.15, y: y + 0.15, w: w - 0.3, h: 0.45, fontFace: MONO, fontSize: 10, color: c, charSpacing: 1 });
    if (i < 4) arrow(s, x + w + 0.03, y + h / 2, col[i + 1][0] - 0.03, y + h / 2, SILVER);
  });
  T(s, [
    { text: "ORV-0009", options: { fontFace: MONO, fontSize: 13, color: ICE, breakLine: true } },
    { text: "Trade note: Orvan to Midgard, wheat", options: { fontSize: 13, breakLine: true } },
    { text: "tier 1 · 2027-01-19", options: { fontSize: 11, color: SILVER } },
  ], { x: M + 0.15, y: y + 0.7, w: 1.6, h: 1.8 });
  T(s, [
    { text: "Sep–Dec 2026", options: { fontSize: 12, color: SILVER, breakLine: true } },
    { text: "R3 R4 R5 R6", options: { fontFace: MONO, fontSize: 13, color: ICE, breakLine: true } },
    { text: " ", options: { fontSize: 8, breakLine: true } },
    { text: "Sep–Dec 2025", options: { fontSize: 12, color: SILVER, breakLine: true } },
    { text: "R9 R10 R11 R12", options: { fontFace: MONO, fontSize: 13, color: ICE } },
  ], { x: 2.95, y: y + 0.7, w: 1.65, h: 1.9 });
  T(s, [
    { text: "CALC-2471c1  ·  yoy_change", options: { fontFace: MONO, fontSize: 12, color: ICE, breakLine: true } },
    { text: "sum(current) − sum(prior)", options: { fontFace: MONO, fontSize: 12, color: SILVER, breakLine: true } },
    { text: "142.1 − 358.3 = −216.2 USD M", options: { fontFace: MONO, fontSize: 13, color: IVORY, breakLine: true } },
    { text: " ", options: { fontSize: 8, breakLine: true } },
    { text: "CALC-cb98e8  ·  Oct–Dec only", options: { fontFace: MONO, fontSize: 12, color: ICE, breakLine: true } },
    { text: "103.9 − 260.4 = −156.5 USD M", options: { fontFace: MONO, fontSize: 13, color: IVORY, breakLine: true } },
    { text: " ", options: { fontSize: 8, breakLine: true } },
    { text: "inputs kept · excluded rows: none", options: { fontSize: 11, color: SILVER } },
  ], { x: 5.15, y: y + 0.6, w: 3.45, h: 2.1 });
  T(s, [
    { text: "156.5 – 216.2", options: { fontFace: "Garamond", fontSize: 24, color: GOLD, breakLine: true } },
    { text: "USD M  ·  Midgard wheat", options: { fontSize: 12, color: IVORY, breakLine: true } },
    { text: " ", options: { fontSize: 6, breakLine: true } },
    { text: "Odin's range: the year-on-year fall in import value", options: { fontSize: 11, color: SILVER } },
  ], { x: 9.15, y: y + 0.65, w: 1.8, h: 1.95 });
  T(s, [
    { text: "Inline citation", options: { fontSize: 12, color: SILVER, breakLine: true } },
    { text: "[ORV-0009 R3,", options: { fontFace: MONO, fontSize: 11, color: ICE, breakLine: true } },
    { text: " 2027-01-19]", options: { fontFace: MONO, fontSize: 11, color: ICE } },
  ], { x: 11.5, y: y + 0.65, w: 1.15, h: 1.6 });
  // rules
  const rs = [
    ["The model picks rows and an operation. Python computes the result and keeps the inputs.", ICE],
    ["Each bound must equal a cited calculation result, and both bounds must be the same kind of calculation.", ICE],
    ["Trade value at risk is not economic loss. A missing value is never treated as zero.", CRIM],
  ];
  const rw = (CW - 2 * 0.35) / 3;
  rs.forEach(([t, c], i) => {
    const x = M + i * (rw + 0.35);
    s.addShape(S.RECTANGLE, { x, y: 5.22, w: 0.1, h: 0.1, fill: { color: c }, line: { color: c, width: 0 } });
    T(s, t, { x: x + 0.25, y: 5.1, w: rw - 0.25, h: 0.85, fontSize: 14, color: IVORY });
  });
  T(s, "Every estimate states metric, unit, period, denominator, assumptions, missing data and confidence.   Figures from " + CASE + ".", { x: M, y: 6.35, w: CW, h: 0.45, fontSize: 11, color: SILVER });
  s.addNotes(
`KEY POINT: Every number in a briefing can be replayed from cited rows by deterministic code.

SCRIPT: Models are unreliable at arithmetic, so they do none. Here is a real chain from our saved case. Trade note ORV-0009, a tier-1 document, supplies eight monthly rows: September to December of 2026 and of 2025. A Python function computes the year-on-year change: 142.1 minus 358.3, a fall of 216.2 million dollars. A second record covers October to December: 156.5. Odin's range for Midgard wheat is exactly those two results, cited inline with dates. And this is trade value at risk, not an economic loss estimate.

TRANSITION: Here is what all of this looks like in the product.

IF ASKED: Operations are sum, mean, share, yoy_change, yoy_pct_change, period_change and net_offset. Each record keeps its input rows, any excluded rows with the reason, the formula and the result, and replays identically. Code rejects a range whose bounds come from different kinds of calculation, for example a sum joined to a year-on-year change.`);
}

// ================================================================== 8. Product
{
  const s = content("Proof");
  eyebrowTitle(s, "THE PRODUCT IN ACTION", "From investigation to decision-ready intelligence");
  // left: argument map
  const cap = (k, d, x, y, w) => T(s, [
    { text: k, options: { fontFace: MONO, fontSize: 10, color: ICE, charSpacing: 2, breakLine: true } },
    { text: d, options: { fontSize: 12, color: IVORY } },
  ], { x, y, w, h: 0.62 });
  const frame = (img, x, y, w, h) => {
    s.addImage({ path: A(img), x, y, w, h });
    s.addShape(S.RECTANGLE, { x, y, w, h, fill: { color: OBS, transparency: 100 }, line: { color: LINE, width: 0.75 } });
  };
  const lx = M, ly = 1.9, lw = 6.3, lh = lw / 1.56;
  frame("thumb_map.png", lx, ly, lw, lh);
  cap("ARGUMENT MAP", "Cited documents → claims → attacks → responses → Odin's rulings, one lane per claim", lx, ly + lh + 0.12, lw);
  // right: exposure + reader
  const rx = 7.25, rw = W - M - rx, eh = rw / 1.89;
  frame("shot_exposure.png", rx, ly, rw, eh);
  cap("EXPOSURE", "Thor, Loki and Odin on one axis; missing is never drawn as zero", rx, ly + eh + 0.12, rw);
  const ry = ly + eh + 0.85, rh = 1.25, rww = rh * 1.55;
  frame("thumb_reader.png", rx, ry, rww, rh);
  T(s, [
    { text: "CLICK-THROUGH", options: { fontFace: MONO, fontSize: 10, color: ICE, charSpacing: 2, breakLine: true } },
    { text: "Any citation opens the source with the cited paragraph highlighted.", options: { fontSize: 12, color: IVORY, breakLine: true } },
    { text: "Real captures, saved two-run case.", options: { fontSize: 11, color: SILVER } },
  ], { x: rx + rww + 0.25, y: ry, w: rw - rww - 0.25, h: rh });
  s.addNotes(
`KEY POINT: It is a working, inspectable application; every element on screen is a recorded event or a stored document.

SCRIPT: These are real captures from the saved case. On the left, the argument map: each lane runs from the cited documents, to the claim, to the attack, the response, and Odin's ruling, so you can see the whole debate at once. Top right, the exposure view: Thor's, Loki's and Odin's ranges on one shared axis. Where there is no evidence, it says no estimate, and the reason. It never draws a zero. Bottom right, click-through: any citation opens the source document with the cited paragraph highlighted, so a judge can check every claim in two clicks.

TRANSITION: A system like this must also know what it should not use.

IF ASKED: The dashboard has six views: Trial, Argument map, Exposure, Evidence, Briefing and Run trace. It follows the case live over Server-Sent Events with a polling fallback, and nothing on screen is simulated.`);
}

// ================================================================== 9. Safety
{
  const s = content("Proof");
  eyebrowTitle(s, "EVIDENCE, SAFETY AND TRUST", "The system must know what it cannot safely use");
  // flow: documents -> 4 gates -> agents / briefing
  T(s, "DOCUMENTS", { x: M, y: 2.0, w: 1.3, h: 0.3, fontFace: MONO, fontSize: 10, color: SILVER, charSpacing: 2 });
  T(s, "PDF · TXT · DOCX, packs and uploads", { x: M, y: 2.32, w: 1.3, h: 0.8, fontSize: 12, color: IVORY });
  const gates = [
    ["VALIDATED INGEST", "Type and size checked, safe file names. The original is kept with its content hash. Damaged files and rows are flagged, never used as valid numbers.", ""],
    ["INJECTION SCAN", "Role labels and override phrases are flagged. The span stays on record but is withheld from agent prompts.", "TRAP_INJECTION"],
    ["AS-OF GATE", "Enforced in code on search, reads, trade rows, calculations and citations. A later document is refused (HTTP 403).", "CLOCK_VIOLATION_BLOCKED"],
    ["CITATION CHECK", "At briefing build: the paragraph or row exists, the quote matches, the date is in the window. Failures are dropped and listed.", ""],
  ];
  const gx0 = 2.15, gw = 2.18, gg = 0.2, gy = 1.95, gh = 3.25;
  gates.forEach(([k, d, ev], i) => {
    const x = gx0 + i * (gw + gg);
    box(s, x, gy, gw, gh, { line: { color: ICED, width: 1 } });
    s.addShape(S.RECTANGLE, { x: x + 0.2, y: gy + 0.22, w: 0.05, h: 0.38, fill: { color: ICE }, line: { color: ICE, width: 0 } });
    s.addShape(S.RECTANGLE, { x: x + 0.31, y: gy + 0.22, w: 0.05, h: 0.38, fill: { color: ICE }, line: { color: ICE, width: 0 } });
    T(s, k, { x: x + 0.5, y: gy + 0.2, w: gw - 0.6, h: 0.45, fontFace: MONO, fontSize: 10, color: ICE, charSpacing: 1, valign: "middle" });
    T(s, d, { x: x + 0.2, y: gy + 0.82, w: gw - 0.35, h: 1.9, fontSize: 13, color: IVORY });
    if (ev) T(s, ev, { x: x + 0.2, y: gy + gh - 0.45, w: gw - 0.3, h: 0.25, fontFace: MONO, fontSize: 9, color: CRIM });
  });
  const ex = gx0 + 4 * (gw + gg) - gg;
  arrow(s, 1.9, 3.55, gx0 - 0.02, 3.55, SILVER);
  arrow(s, ex + 0.02, 3.55, ex + 0.3, 3.55, SILVER);
  T(s, "AGENTS", { x: ex + 0.38, y: 2.0, w: W - M - ex - 0.38, h: 0.3, fontFace: MONO, fontSize: 10, color: SILVER, charSpacing: 2 });
  T(s, "see only wrapped evidence", { x: ex + 0.38, y: 2.32, w: W - M - ex - 0.38, h: 1.0, fontSize: 12, color: IVORY });
  // bottom band
  const bw = (CW - 0.35) / 2;
  T(s, [{ text: "TRANSPARENT UNCERTAINTY", options: { fontFace: MONO, fontSize: 10, color: GOLD, charSpacing: 2, breakLine: true } }, { text: "No estimate is shown as missing, never as zero. A briefing is labelled complete, partial or incomplete; it never claims completeness falsely.", options: { fontSize: 13, color: IVORY } }], { x: M, y: 5.55, w: bw, h: 1.1 });
  T(s, [{ text: "EVERYTHING ON THE RECORD", options: { fontFace: MONO, fontSize: 10, color: ICE, charSpacing: 2, breakLine: true } }, { text: "Append-only audit log in SQLite with JSONL export. Corrections, retractions and duplicates stay linked to the reports they affect.", options: { fontSize: 13, color: IVORY } }], { x: M + bw + 0.35, y: 5.55, w: bw, h: 1.1 });
  s.addNotes(
`KEY POINT: Safety is enforced in code at four gates, and uncertainty is shown, not hidden.

SCRIPT: Every document passes four gates before it can influence anything. Ingest validates files, keeps the original with its content hash, and flags damage instead of repairing it silently. An injection scanner flags text such as a fake SYSTEM instruction; the span stays on record, is shown on the dashboard, but never reaches an agent's prompt. The as-of gate is enforced on every path, so a document published after the question's date is refused and the attempt logged. Finally, when the briefing is built, every citation is checked again and anything that fails is dropped and listed. And when evidence is missing, the system says so. It labels briefings complete, partial or incomplete.

TRANSITION: Here is how those pieces fit together technically.

IF ASKED: Tests show that a malicious document cannot skip cross-examination, change the question or the as-of date, force Odin to establish a claim, or force endless send-backs. We make no claim of being hallucination-free; we make every claim checkable.`);
}

// ================================================================== 10. Architecture
{
  const s = content("Proof");
  eyebrowTitle(s, "TECHNICAL ARCHITECTURE", "A transparent application around a specialised agent workflow");
  const lx = M, lw = 1.75, cx = M + lw + 0.2, cwid = W - M - cx;
  const rows = [
    ["FRONTEND", ICE, [["Dashboard", "React · Vite · TypeScript · Tailwind"], ["Six views", "Trial · Argument map · Exposure · Evidence · Briefing · Run trace"], ["Case state", "typed API client, live event stream"]]],
    ["API", ICE, [["FastAPI on Uvicorn", "POST /cases · GET /cases/{id} · /resume"], ["Live updates", "/events Server-Sent Events, polling fallback"], ["Evidence access", "/docs · /trade · /feed · POST /ingest"]]],
    ["AGENT LAYER", GOLD, [["Trial state machine", "explicit stages, checked transitions, run limit"], ["Four agents", "own prompt and tool allow-list; Pydantic-validated output, one repair"], ["LLM client", "Gemini by default, Anthropic optional; model chain, budgets, reply cache"]]],
    ["EVIDENCE AND AUDIT", ICE, [["Ingest", "PDF · TXT · DOCX, trade tables, damage and injection flags"], ["Hybrid retrieval", "BM25 + bge-small vectors, RRF, metadata filters, as-of gate"], ["Calculations + store", "deterministic records; SQLite audit log, memories and caches"]]],
  ];
  const rh = 0.98, rg = 0.17, y0 = 1.95;
  rows.forEach(([k, col, cells], i) => {
    const y = y0 + i * (rh + rg);
    T(s, k, { x: lx, y, w: lw, h: rh, fontFace: MONO, fontSize: 10, color: col, charSpacing: 2, valign: "middle" });
    const cg = 0.15, cellw = (cwid - 2 * cg) / 3;
    cells.forEach(([h, d], j) => {
      const x = cx + j * (cellw + cg);
      box(s, x, y, cellw, rh, { line: { color: i === 2 ? GOLD : LINE, width: 0.75 } });
      T(s, h, { x: x + 0.15, y: y + 0.1, w: cellw - 0.3, h: 0.28, fontSize: 13, bold: true, color: IVORY });
      T(s, d, { x: x + 0.15, y: y + 0.4, w: cellw - 0.3, h: 0.55, fontSize: 11, color: SILVER });
    });
    if (i < 3) arrow(s, cx + cwid / 2, y + rh + 0.01, cx + cwid / 2, y + rh + rg - 0.01, SILVER, { beginArrowType: "triangle" });
  });
  T(s, "Logical view. Runs locally as two processes (API on :8000, dashboard on :5173). 382 automated tests use a scripted model.", { x: M, y: 6.62, w: CW, h: 0.25, fontSize: 11, color: SILVER });
  s.addNotes(
`KEY POINT: The architecture is a plain, inspectable stack; the intelligence sits in a small, code-governed agent layer.

SCRIPT: The dashboard is React, Vite, TypeScript and Tailwind. It talks only to a FastAPI backend on Uvicorn and follows a case live through Server-Sent Events, with polling as a fallback. Inside, an explicit state machine runs the trial. Each agent has its own prompt and tool allow-list, and every model reply is validated against a Pydantic schema. The client defaults to Gemini and can pause and resume a case without losing work. Underneath: ingestion, hybrid BM25 and vector retrieval, deterministic calculations, and a SQLite audit log.

TRANSITION: Let me show you one case from start to finish.

IF ASKED: Retrieval fuses BM25 and one vector index (bge-small-en-v1.5, local, via fastembed) with Reciprocal Rank Fusion, plus filters on country, sector, event, source type, reliability tier and dates. A two-run case uses about 22 to 25 model requests. This diagram is logical; we have not deployed to production.`);
}

// ================================================================== 11. Demo + limitations
pres.addSection({ title: "Close" });
{
  const s = content("Close");
  eyebrowTitle(s, "DEMONSTRATION", "Follow one case from question to judgment");
  const steps = [
    ["thumb_ask.png", "Ask", "question and as-of date"],
    ["thumb_casefile.png", "Investigate", "Heimdall's case file"],
    ["thumb_map.png", "Argue", "claims, attacks, rulings"],
    ["thumb_reader.png", "Verify", "open a cited source"],
    ["thumb_exposure.png", "Measure", "ranges and calculations"],
    ["thumb_trace.png", "Trace", "send-back, run 2, memory"],
    ["thumb_briefing.png", "Brief", "report and exports"],
  ];
  const tw = 1.6, tg = (CW - 7 * tw) / 6, th = tw / 1.56, ty = 1.9;
  steps.forEach(([img, k, d], i) => {
    const x = M + i * (tw + tg);
    s.addImage({ path: A(img), x, y: ty, w: tw, h: th, sizing: { type: "cover", w: tw, h: th } });
    s.addShape(S.RECTANGLE, { x, y: ty, w: tw, h: th, fill: { color: OBS, transparency: 100 }, line: { color: LINE, width: 0.75 } });
    T(s, [{ text: `${i + 1}  `, options: { fontFace: MONO, fontSize: 11, color: ICE } }, { text: k, options: { fontSize: 14, bold: true, color: IVORY } }], { x, y: ty + th + 0.1, w: tw, h: 0.3 });
    T(s, d, { x, y: ty + th + 0.4, w: tw, h: 0.45, fontSize: 11, color: SILVER });
    if (i < 6) arrow(s, x + tw + 0.02, ty + th / 2, x + tw + tg - 0.02, ty + th / 2, ICED, { width: 1 });
  });
  // what the saved case shows
  T(s, "THE SAVED TWO-RUN CASE, A REAL GEMINI RUN ON THE DEV PACK", { x: M, y: 3.95, w: CW, h: 0.25, fontFace: MONO, fontSize: 10, color: ICE, charSpacing: 2 });
  const facts = [["24", "model requests"], ["9", "claims ruled"], ["8", "attacks, 4 each way"], ["13", "new references in run 2"], ["6", "logged memory changes"]];
  const fw = CW / 5;
  facts.forEach(([n, d], i) => {
    const x = M + i * fw;
    T(s, n, { x, y: 4.22, w: fw - 0.1, h: 0.6, fontFace: "Garamond", fontSize: 34, color: IVORY });
    T(s, d, { x, y: 4.82, w: fw - 0.1, h: 0.3, fontSize: 12, color: SILVER });
  });
  // limitations
  box(s, M, 5.35, CW, 1.5, { fill: { color: PANEL, transparency: 20 } });
  T(s, "LIMITATIONS", { x: M + 0.2, y: 5.48, w: 3, h: 0.25, fontFace: MONO, fontSize: 10, color: CRIM, charSpacing: 2 });
  const lim = ["Conclusions are only as good as the evidence available.", "Cases can stay incomplete. This one did: no Tolan maize data is in the pack.", "Argument quality depends on the model; claims still need scrutiny.", "Daily model quotas can pause a run until the reset.", "A second run does not guarantee new evidence."];
  const lw2 = (CW - 0.6) / 2;
  T(s, lim.slice(0, 3).map((t, j) => ({ text: t, options: { bullet: { indent: 12 }, breakLine: j < 2 } })), { x: M + 0.2, y: 5.8, w: lw2, h: 1.0, fontSize: 12, color: IVORY, paraSpaceAfter: 3 });
  T(s, lim.slice(3).map((t, j) => ({ text: t, options: { bullet: { indent: 12 }, breakLine: j < 1 } })), { x: M + 0.4 + lw2, y: 5.8, w: lw2, h: 1.0, fontSize: 12, color: IVORY, paraSpaceAfter: 3 });
  s.addNotes(
`KEY POINT: One real case shows the whole loop, including an honest "incomplete" result.

SCRIPT: In the demo we ask the sample question with its as-of date. Heimdall confirms the event and notes a corrected renewal report. Thor and Loki submit nine claims, attack each other eight times, and Odin rules on every claim. We open a citation, then the calculation behind a range. Odin sent the case back; in run 2 Heimdall found thirteen genuinely new references and the advocates revised their claims. Tolan maize data is not in the pack, so the briefing is labelled incomplete. That is the correct answer, stated plainly, in 24 model requests.

TRANSITION: To close.

IF ASKED: Memory: Heimdall's lessons from earlier cases added searches for correction and retraction notices; the log records the plan without memory, the plan with it, and the lesson used. Paused cases resume after the quota reset, and finished steps replay from a reply cache with no new requests.`);
}

// ================================================================== 12. Closing
{
  const s = pres.addSlide({ masterName: "CLOSE", sectionTitle: "Close" });
  T(s, "When the evidence is contested,\nthe decision must be earned.", { x: 1, y: 0.55, w: W - 2, h: 1.55, fontFace: "Garamond", fontSize: 40, color: IVORY, align: "center", valign: "middle" });
  T(s, "Research the event.  Challenge the claims.  Trace the numbers.  Judge the evidence.", { x: 1, y: 2.15, w: W - 2, h: 0.4, fontSize: 15, color: GOLD, align: "center", charSpacing: 1 });
  T(s, "RAGNAROK  ·  TRIAL OF THE NINE REALMS", { x: M, y: 6.85, w: 7, h: 0.3, fontFace: MONO, fontSize: 10, color: SILVER, charSpacing: 2 });
  T(s, "Questions?", { x: W - M - 3, y: 6.75, w: 3, h: 0.4, fontFace: "Garamond", italic: true, fontSize: 20, color: IVORY, align: "right" });
  s.addNotes(
`KEY POINT: Leave the judges with the differentiator: a decision that is earned through research, challenge, verification and judgment.

SCRIPT: Ragnarok is not one model answering a question. It is an investigation: an investigator that names what it does not know, two advocates who must defend every claim against attack, code that does the arithmetic, and a judge who rules from the evidence and sends the case back when the evidence is not enough. When the evidence is contested, the decision must be earned. Thank you. We are happy to take questions, or to open any claim in the live dashboard.

TRANSITION: Questions.

IF ASKED: The saved two-run case, its logs, the README and the dashboard guide are all in the repository, and a judge can open any citation in the case.`);
}

// ================================================================== Appendix A
pres.addSection({ title: "Appendix" });
{
  const s = content("Appendix");
  eyebrowTitle(s, "APPENDIX A  ·  TECHNICAL REFERENCE", "Endpoints, live updates and ingestion");
  const hdr = (t) => ({ text: t, options: { fontFace: MONO, fontSize: 10, color: "76B9FF", bold: false, fill: { color: "1A1F2A" } } });
  const r = (a, b) => [{ text: a, options: { fontFace: MONO, fontSize: 11, color: "E8E5DC" } }, { text: b, options: { fontSize: 12, color: "9299A6" } }];
  const rows = [
    [hdr("ENDPOINT"), hdr("PURPOSE")],
    r("POST /cases", "start a case (one at a time)"),
    r("GET /cases/{id}", "status and results"),
    r("GET /cases/{id}/events", "Server-Sent Events of the audit log"),
    r("POST /cases/{id}/resume", "resume a failed, partial or paused case"),
    r("GET /docs/{id}[/{para}]", "documents, as-of gated"),
    r("GET /trade/{table}[/{row}]", "trade rows, as-of gated"),
    r("GET /feed?as_of=", "documents with tier, correction, damage badges"),
    r("POST /ingest", "pack .zip or loose PDF, TXT, DOCX"),
  ];
  s.addTable(rows, { x: M, y: 1.95, w: 6.6, colW: [2.75, 3.85], rowH: 0.42, border: { type: "solid", color: "2E3646", pt: 0.75 }, fill: { color: "141821" }, valign: "middle", margin: [0.04, 0.1, 0.04, 0.1] });
  const rx = 7.6, rw = W - M - rx;
  const blocks = [
    ["LIVE UPDATES", "The dashboard follows /events over Server-Sent Events and falls back to polling. Every visible action is a recorded event."],
    ["INGESTION FLOW", "Manifest and header parse → text extraction with segment-wise encoding detection → [Pn] paragraphs and trade rows → damage, injection, duplicate and correction flags → hybrid index. New packs need no code changes."],
    ["OUTPUTS PER CASE", "state, case file, claims, cross-examination, rulings, per-run folders, briefing (.md, .json), memory, model-request ledger, events.jsonl."],
  ];
  let y = 1.95;
  blocks.forEach(([k, d]) => {
    T(s, k, { x: rx, y, w: rw, h: 0.25, fontFace: MONO, fontSize: 10, color: ICE, charSpacing: 2 });
    T(s, d, { x: rx, y: y + 0.3, w: rw, h: 1.2, fontSize: 13, color: IVORY });
    y += 1.55;
  });
  s.addNotes(
`KEY POINT: Reference slide for technical questions; not presented in the main pitch.

SCRIPT: Use only if a judge asks about the API or data flow. The interactive API documentation is served at /api/docs. All document and trade paths are gated by the case's as-of date; a later document returns HTTP 403 and is logged as CLOCK_VIOLATION_BLOCKED.

TRANSITION: Back to questions, or Appendix B for design decisions.

IF ASKED: Unseen packs were tested with a random pack generator: three seeds, each 26 of 26 ingest checks passing, and full trials on two of them.`);
}

// ================================================================== Appendix B
{
  const s = content("Appendix");
  eyebrowTitle(s, "APPENDIX B  ·  DESIGN DECISIONS", "Why the investigation is split into stages");
  const ds = [
    ["Separate research from argument", "Heimdall establishes the facts and the gaps before anyone takes a side, so advocates start from the same case file."],
    ["Two opposing advocates", "Thor and Loki search independently; the argument for limited exposure is never an afterthought."],
    ["Cross-examination with rules", "Attacks need a target and counter-evidence or a named gap. Defenses need new evidence, or they concede."],
    ["A judge who cannot search", "Odin rules from the record. He names missing evidence and can send the case back, but never assigns work."],
    ["Arithmetic in code", "Replayable calculation records make every number in the briefing checkable."],
    ["Private memory per agent", "General lessons carry across cases. The log shows the plan without memory and with it, so influence is visible."],
  ];
  const cw2 = (CW - 0.4) / 2;
  ds.forEach(([k, d], i) => {
    const x = M + (i % 2) * (cw2 + 0.4), y = 1.95 + Math.floor(i / 2) * 1.12;
    T(s, k, { x, y, w: cw2, h: 0.32, fontSize: 15, bold: true, color: IVORY });
    T(s, d, { x, y: y + 0.36, w: cw2, h: 0.7, fontSize: 13, color: SILVER });
  });
  box(s, M, 5.45, CW, 1.3, { line: { color: LINE, width: 0.75, dashType: "dash" }, fill: { color: PANEL, transparency: 40 } });
  T(s, "NOT IMPLEMENTED  ·  POSSIBLE NEXT STEPS", { x: M + 0.2, y: 5.58, w: 6, h: 0.25, fontFace: MONO, fontSize: 10, color: SILVER, charSpacing: 2 });
  T(s, "OCR for scanned PDFs (today they are ingested as empty, damaged documents)  ·  non-English documents  ·  Odin building ranges that differ from both advocates more often  ·  more than one case at a time per API process", { x: M + 0.2, y: 5.9, w: CW - 0.4, h: 0.8, fontSize: 13, color: IVORY });
  s.addNotes(
`KEY POINT: Each structural choice exists to make a specific failure visible or impossible; future work is labelled as such.

SCRIPT: Use only if asked why the architecture looks like this. Every stage answers a failure mode: incomplete evidence (Heimdall and the send-back), one-sided interpretation (two advocates plus cross-examination), unverifiable numbers (code-only arithmetic), and unearned conclusions (Odin rules claim by claim and labels the briefing honestly).

TRANSITION: Back to questions.

IF ASKED: Known limitation from our own testing: Odin often adopts the better-supported advocate's range rather than building a different one. Code ensures his bounds reproduce from calculation records, but it is an honest observation.`);
}

(async () => {
  await pres.writeFile({ fileName: OUT });
  await applyTheme(OUT, THEME);
  console.log("wrote", OUT);
})();
