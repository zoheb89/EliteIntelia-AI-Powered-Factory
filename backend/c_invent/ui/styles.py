import streamlit as st


THEMES = {"System", "Light", "Dark"}


def inject_css(theme: str = "System"):
    """Inject an adaptive EliteInteliA UI theme.

    System follows the browser/OS preference. Light and Dark are explicit
    overrides exposed in the application sidebar.
    """
    theme = theme.title() if theme else "System"
    if theme not in THEMES:
        theme = "System"

    light = {
        "bg": "#f7f9fc", "surface": "#ffffff", "surface2": "#f2f5f8",
        "text": "#17212b", "muted": "#667085", "subtle": "#8a94a3",
        "line": "#dfe5ec", "line2": "#cfd8e3", "accent": "#0b9f6a",
        "accent2": "#078aa5", "accentSoft": "#e8f7f1", "accentSoft2": "#e8f7fa",
        "danger": "#d94841", "warning": "#b7791f", "success": "#16845b",
        "sidebar": "#ffffff", "sidebarText": "#263342", "sidebarMuted": "#6b7785",
        "hero1": "#f3faf7", "hero2": "#eef8fb", "shadow": "rgba(15,23,42,.06)",
    }
    dark = {
        "bg": "#0b1118", "surface": "#111a24", "surface2": "#172331",
        "text": "#edf3f7", "muted": "#a9b7c4", "subtle": "#80909f",
        "line": "#263646", "line2": "#34485a", "accent": "#32d296",
        "accent2": "#32c6df", "accentSoft": "#103529", "accentSoft2": "#10333b",
        "danger": "#ff786e", "warning": "#e6b85c", "success": "#54d7a0",
        "sidebar": "#0d151e", "sidebarText": "#e7eef5", "sidebarMuted": "#94a6b5",
        "hero1": "#102a23", "hero2": "#102a34", "shadow": "rgba(0,0,0,.24)",
    }

    def vars_for(p):
        return ";".join(f"--eia-{k}:{v}" for k, v in p.items())

    base_vars = vars_for(light)
    dark_vars = vars_for(dark)
    if theme == "Dark":
        theme_css = f":root{{{dark_vars}}}"
    elif theme == "Light":
        theme_css = f":root{{{base_vars}}}"
    else:
        theme_css = f":root{{{base_vars}}}@media (prefers-color-scheme:dark){{:root{{{dark_vars}}}}}"

    st.markdown(f"""
    <style>
    {theme_css}

    html, body, .stApp, [data-testid="stAppViewContainer"],
    [data-testid="stHeader"], [data-testid="stToolbar"] {{
        font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif !important;
    }}
    .stApp {{ background:var(--eia-bg) !important; color:var(--eia-text) !important; }}
    .stApp h1,.stApp h2,.stApp h3,.stApp h4,.stApp h5,.stApp h6,
    .stApp p,.stApp li,.stApp label,.stApp [data-testid="stMarkdownContainer"],
    .stApp button,.stApp input,.stApp textarea,.stApp select {{
        font-family:inherit !important; color:var(--eia-text);
    }}
    .stApp h1{{font-size:2rem !important;line-height:1.15 !important;font-weight:800 !important;letter-spacing:-.02em !important}}
    .stApp h2{{font-size:1.45rem !important;line-height:1.2 !important;font-weight:800 !important}}
    .stApp h3{{font-size:1.12rem !important;line-height:1.25 !important;font-weight:800 !important}}
    .stApp h4{{font-size:.98rem !important;line-height:1.3 !important;font-weight:750 !important}}
    .stApp p,.stApp li,.stApp label,.stApp .stCaption{{font-size:.90rem;line-height:1.45}}
    .stApp .stCaption,.stApp [data-testid="stCaptionContainer"]{{color:var(--eia-muted) !important}}

    /* Native Streamlit surfaces */
    [data-testid="stAppViewContainer"], [data-testid="stMainBlockContainer"] {{ background:var(--eia-bg) !important; }}
    [data-testid="stHeader"]{{background:transparent !important}}
    [data-testid="stToolbar"]{{background:transparent !important}}
    [data-testid="stSidebar"]{{
        background:var(--eia-sidebar) !important;border-right:1px solid var(--eia-line) !important;
    }}
    [data-testid="stSidebar"] *{{color:var(--eia-sidebarText) !important}}
    [data-testid="stSidebar"] .stCaption,
    [data-testid="stSidebar"] [data-testid="stCaptionContainer"]{{color:var(--eia-sidebarMuted) !important}}
    [data-testid="stSidebar"] hr{{border-color:var(--eia-line) !important}}
    [data-testid="stSidebar"] .stButton button{{
        background:transparent !important;border:1px solid transparent !important;
        text-align:left !important;border-radius:10px !important;color:var(--eia-sidebarText) !important;
    }}
    [data-testid="stSidebar"] .stButton button:hover{{
        background:var(--eia-surface2) !important;border-color:var(--eia-line) !important;
    }}
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong{{
        color:var(--eia-sidebarMuted) !important;letter-spacing:.08em;font-size:.72rem !important;
    }}
    [data-testid="stSidebar"] input,[data-testid="stSidebar"] textarea,
    [data-testid="stSidebar"] [data-baseweb="select"] > div{{
        background:var(--eia-surface) !important;color:var(--eia-text) !important;
        border-color:var(--eia-line2) !important;
    }}

    /* Controls */
    .stApp .stButton button{{font-size:.88rem !important;font-weight:700 !important;line-height:1.2 !important}}
    .stApp .stButton button[kind="primary"]{{
        background:linear-gradient(90deg,var(--eia-accent),var(--eia-accent2)) !important;
        border-color:var(--eia-accent) !important;color:#fff !important;
    }}
    .stApp .stButton button[kind="primary"] p{{color:#fff !important}}
    .stApp input,.stApp textarea,[data-baseweb="select"] > div,[data-baseweb="input"] > div{{
        background:var(--eia-surface) !important;color:var(--eia-text) !important;border-color:var(--eia-line2) !important;
    }}
    .stApp input::placeholder,.stApp textarea::placeholder{{color:var(--eia-subtle) !important}}
    [data-testid="stMetric"]{{
        background:var(--eia-surface) !important;border:1px solid var(--eia-line) !important;
        border-radius:12px !important;box-shadow:0 3px 12px var(--eia-shadow) !important;
    }}

    /* Brand */
    .brand-lockup{{display:flex;align-items:center;gap:11px;padding:4px 2px 17px;margin-bottom:10px}}
    .brand-mark{{
        width:34px;height:34px;border-radius:10px;background:linear-gradient(135deg,var(--eia-accent),var(--eia-accent2));
        color:#06131d;display:flex;align-items:center;justify-content:center;font-size:20px;font-weight:900;
        box-shadow:0 7px 20px rgba(6,182,212,.18)
    }}
    .brand-name{{font-size:19px;font-weight:850;letter-spacing:-.03em;color:var(--eia-text) !important;line-height:1.05}}
    .brand-sub{{font-size:8px;letter-spacing:.17em;color:var(--eia-sidebarMuted) !important;font-weight:800;margin-top:3px}}

    /* Hero / reusable cards */
    .hero{{
        padding:1.2rem 1.5rem;border:1px solid var(--eia-line);border-radius:18px;
        background:linear-gradient(135deg,var(--eia-hero1),var(--eia-hero2));margin-bottom:1.2rem;
        box-shadow:0 14px 40px var(--eia-shadow);color:var(--eia-text) !important;
    }}
    .hero h1{{font-size:2rem !important;margin:.2rem 0 !important;color:var(--eia-text) !important}}
    .hero p{{color:var(--eia-muted) !important;margin:0}}
    .eyebrow{{font-size:.72rem;letter-spacing:.12em;font-weight:800;color:var(--eia-accent2) !important}}
    .metric-card,.scope-card,.ui-card{{
        border:1px solid var(--eia-line);border-radius:14px;background:var(--eia-surface);
        padding:14px 16px;margin:6px 0 10px;box-shadow:0 1px 2px var(--eia-shadow);
    }}
    .metric-card{{min-height:105px}}
    .metric-label{{font-size:13px;font-weight:700;color:var(--eia-muted);margin-bottom:5px}}
    .metric-value{{font-size:28px;font-weight:800;color:var(--eia-text);line-height:1.05}}
    .metric-hint,.ui-card-sub{{font-size:12px;color:var(--eia-muted);margin-top:8px;line-height:1.45}}
    .scope-card{{min-height:105px}}
    .scope-title,.ui-card-title{{font-weight:800;font-size:15px;color:var(--eia-text);margin-bottom:7px}}
    .scope-text{{color:var(--eia-muted);font-size:13px;line-height:1.45}}
    .evidence-chip,.arch-chip{{display:inline-block;padding:4px 8px;border-radius:999px;background:var(--eia-surface2);font-size:11px;font-weight:700;color:var(--eia-muted)}}

    /* Lifecycle */
    .stepper{{display:flex;gap:8px;overflow-x:auto;padding:10px 2px 16px;margin:6px 0 18px;scrollbar-width:thin}}
    .stage{{min-width:118px;flex:1 0 118px;padding:12px 10px;border:1px solid var(--eia-line);border-radius:12px;background:var(--eia-surface);text-align:center;position:relative;color:var(--eia-text)}}
    .stage-icon{{font-size:18px;font-weight:800;line-height:1.1;margin-bottom:7px}}
    .stage-label{{font-size:13px;font-weight:700;line-height:1.25}}
    .stage.done{{border-color:var(--eia-success);background:var(--eia-accentSoft)}}
    .stage.current{{border-color:var(--eia-accent);background:var(--eia-accentSoft);box-shadow:0 0 0 2px rgba(16,185,129,.10)}}
    .stage.locked{{color:var(--eia-muted);background:var(--eia-surface2)}}
    .stage:not(:last-child)::after{{content:'→';position:absolute;right:-12px;top:31px;color:var(--eia-subtle);font-weight:700;z-index:2}}

    /* Architecture */
    .arch-shell{{border:1px solid var(--eia-line);border-radius:18px;background:var(--eia-surface);padding:18px;margin:8px 0 18px;overflow-x:auto}}
    .arch-head{{display:flex;justify-content:space-between;gap:18px;align-items:flex-start;margin-bottom:18px}}
    .arch-eyebrow{{font-size:11px;letter-spacing:.12em;font-weight:800;color:var(--eia-accent2)}}
    .arch-main{{font-size:20px;font-weight:800;margin-top:4px;color:var(--eia-text)}}
    .arch-target{{min-width:250px;padding:12px 14px;border:1px solid var(--eia-line);border-radius:12px;background:var(--eia-surface2);font-size:14px;color:var(--eia-text)}}
    .arch-target span{{color:var(--eia-muted);font-size:12px}}
    .arch-flow{{display:flex;align-items:stretch;gap:0;min-width:1120px}}
    .arch-node-wrap{{display:flex;align-items:stretch;flex:1}}
    .arch-card{{min-width:132px;flex:1;border:1px solid var(--eia-line);background:var(--eia-surface);border-radius:13px;padding:12px;box-shadow:0 1px 2px var(--eia-shadow);color:var(--eia-text)}}
    .arch-key{{font-size:10px;text-transform:uppercase;letter-spacing:.08em;color:var(--eia-subtle);font-weight:800}}
    .arch-title{{font-size:14px;font-weight:800;margin-top:6px;line-height:1.25;color:var(--eia-text)}}
    .arch-detail{{font-size:11px;color:var(--eia-muted);margin-top:7px;line-height:1.4}}
    .arch-arrow{{font-size:22px;font-weight:800;color:var(--eia-subtle);padding:38px 8px 0}}
    .arch-cross{{margin-top:18px;padding-top:14px;border-top:1px dashed var(--eia-line2);font-size:12px;color:var(--eia-muted)}}
    .arch-chip{{margin:7px 5px 0 0;color:var(--eia-muted)}}

    /* Platform scoring */
    .fit-row{{display:grid;grid-template-columns:170px 1fr 72px;gap:12px;align-items:center;margin:9px 0}}
    .fit-name{{font-weight:750;font-size:13px;color:var(--eia-text)}}
    .fit-track{{height:9px;background:var(--eia-surface2);border-radius:99px;overflow:hidden}}
    .fit-fill{{height:100%;background:linear-gradient(90deg,var(--eia-accent),var(--eia-accent2));border-radius:99px}}
    .fit-pct{{text-align:right;font-weight:800;font-size:13px;color:var(--eia-text)}}

    code,pre,[data-testid="stCode"],[data-testid="stJson"]{{font-family:"SFMono-Regular",Consolas,"Liberation Mono",monospace !important}}
    @media(max-width:900px){{
        .stage{{min-width:108px;flex-basis:108px}}
        .stage:not(:last-child)::after{{display:none}}
        .arch-head{{display:block}}
        .arch-target{{margin-top:12px}}
        .arch-flow{{min-width:1000px}}
    }}

    /* ===== EliteInteliA Enterprise UI v0.1.28 ===== */
    :root{{
      --eia-brand-cyan:#10a6a6;
      --eia-brand-blue:#1769e0;
      --eia-ink:#0a1220;
      --eia-ink2:#0c1524;
    }}
    .stApp{{
      background:
        radial-gradient(900px 500px at 85% -10%, color-mix(in srgb,var(--eia-accent) 8%,transparent), transparent 68%),
        radial-gradient(760px 440px at 0% 100%, color-mix(in srgb,var(--eia-accent2) 6%,transparent), transparent 68%),
        var(--eia-bg) !important;
    }}
    /* Give the Streamlit shell the same restrained enterprise density as the React prototype. */
    [data-testid="stMainBlockContainer"]{{
      max-width:1480px !important;
      padding-top:1.1rem !important;
      padding-left:2rem !important;
      padding-right:2rem !important;
    }}
    [data-testid="stSidebar"]{{
      width:264px !important;
      background:var(--eia-sidebar) !important;
    }}
    [data-testid="stSidebar"] > div:first-child{{padding:1rem .75rem !important}}
    .brand-mark{{
      width:38px;height:38px;border-radius:11px;
      background:linear-gradient(135deg,var(--eia-brand-cyan),var(--eia-brand-blue));
      color:#06131d !important;
    }}
    .brand-name{{font-size:16px !important}}
    .brand-name::first-letter{{font-weight:800}}
    .brand-sub{{font-size:9px !important;letter-spacing:.23em !important}}
    /* Sidebar navigation */
    [data-testid="stSidebar"] .stButton{{margin:.12rem 0 !important}}
    [data-testid="stSidebar"] .stButton button{{
      min-height:38px !important;
      padding:.55rem .75rem !important;
      border:1px solid transparent !important;
      border-radius:10px !important;
      font-size:.84rem !important;
      font-weight:600 !important;
      transition:all .15s ease !important;
      box-shadow:none !important;
    }}
    [data-testid="stSidebar"] .stButton button:hover{{
      background:var(--eia-surface2) !important;
      border-color:var(--eia-line) !important;
      transform:none !important;
    }}
    [data-testid="stSidebar"] .stButton button[kind="primary"]{{
      background:linear-gradient(90deg,var(--eia-brand-cyan),var(--eia-brand-blue)) !important;
      color:#fff !important;
    }}
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] strong{{
      font-size:.66rem !important;
      letter-spacing:.12em !important;
      color:var(--eia-sidebarMuted) !important;
    }}
    /* Header/hero */
    .hero{{
      position:relative;
      padding:1.35rem 1.5rem !important;
      border-radius:16px !important;
      background:
        linear-gradient(135deg,
          color-mix(in srgb,var(--eia-accent) 8%,var(--eia-surface)),
          color-mix(in srgb,var(--eia-accent2) 6%,var(--eia-surface))) !important;
      box-shadow:0 12px 32px var(--eia-shadow) !important;
    }}
    .hero::after{{
      content:"";
      position:absolute;right:18px;top:18px;width:9px;height:9px;border-radius:50%;
      background:var(--eia-success);box-shadow:0 0 0 5px color-mix(in srgb,var(--eia-success) 12%,transparent);
    }}
    .hero .eyebrow{{color:var(--eia-accent) !important}}
    /* Cards */
    .metric-card,.scope-card,.ui-card,.arch-shell,.arch-card{{
      transition:border-color .15s ease,box-shadow .15s ease,transform .15s ease;
    }}
    .metric-card:hover,.scope-card:hover,.ui-card:hover,.arch-card:hover{{
      border-color:color-mix(in srgb,var(--eia-accent) 28%,var(--eia-line));
      box-shadow:0 8px 22px var(--eia-shadow);
      transform:translateY(-1px);
    }}
    .metric-card{{
      min-height:112px !important;
      padding:15px 16px !important;
      border-radius:14px !important;
    }}
    .metric-label{{
      font-size:11px !important;text-transform:uppercase;letter-spacing:.04em;
    }}
    .metric-value{{font-size:25px !important}}
    /* Native tabs/expanders/dataframes */
    [data-baseweb="tab-list"]{{
      gap:4px !important;border-bottom:1px solid var(--eia-line) !important;
    }}
    [data-baseweb="tab"]{{
      color:var(--eia-muted) !important;font-weight:650 !important;
    }}
    [data-baseweb="tab"][aria-selected="true"]{{
      color:var(--eia-text) !important;
    }}
    [data-testid="stExpander"]{{
      border:1px solid var(--eia-line) !important;
      border-radius:12px !important;
      background:var(--eia-surface) !important;
    }}
    [data-testid="stDataFrame"]{{
      border:1px solid var(--eia-line) !important;
      border-radius:12px !important;
      overflow:hidden !important;
    }}
    /* Status messages */
    [data-testid="stAlert"]{{
      border-radius:12px !important;
      border:1px solid var(--eia-line) !important;
    }}
    /* Hide Streamlit chrome that competes with the product shell. */
    #MainMenu{{visibility:hidden !important}}
    footer{{visibility:hidden !important}}
    header[data-testid="stHeader"]{{height:0 !important}}
    /* Mobile */
    @media(max-width:900px){{
      [data-testid="stMainBlockContainer"]{{
        padding-left:1rem !important;padding-right:1rem !important;
      }}
      .hero{{padding:1.05rem 1.1rem !important}}
    }}


    /* ===== EliteInteliA True Unified Product Shell v0.1.29 ===== */
    .ei-topbar{{
      display:flex;align-items:center;gap:14px;min-height:58px;margin:0 0 18px;
      padding:9px 12px;border:1px solid var(--eia-line);border-radius:14px;
      background:color-mix(in srgb,var(--eia-surface) 92%,transparent);
      box-shadow:0 8px 26px var(--eia-shadow);backdrop-filter:blur(12px);
      position:sticky;top:8px;z-index:50;
    }}
    .ei-topbar-brand{{display:flex;align-items:center;gap:9px;min-width:230px}}
    .ei-mini-mark{{width:30px;height:30px;border-radius:9px;display:grid;place-items:center;font-size:15px;font-weight:900;color:#06131d;background:linear-gradient(135deg,var(--eia-brand-cyan),var(--eia-brand-blue))}}
    .ei-product-name{{font-size:13px;font-weight:800;color:var(--eia-text);line-height:1.05}}
    .ei-product-sub{{font-size:9px;letter-spacing:.13em;text-transform:uppercase;color:var(--eia-muted);margin-top:3px}}
    .ei-search{{flex:1;max-width:520px;min-width:180px;height:36px;border:1px solid var(--eia-line);border-radius:10px;background:var(--eia-surface2);display:flex;align-items:center;padding:0 12px;color:var(--eia-muted);font-size:12px}}
    .ei-search span{{margin-right:8px;font-size:15px}}
    .ei-top-actions{{margin-left:auto;display:flex;align-items:center;gap:8px}}
    .ei-pill{{border:1px solid var(--eia-line);background:var(--eia-surface2);border-radius:999px;padding:6px 10px;font-size:10px;font-weight:750;color:var(--eia-muted);white-space:nowrap}}
    .ei-pill.live{{color:var(--eia-success);border-color:color-mix(in srgb,var(--eia-success) 30%,var(--eia-line));background:var(--eia-accentSoft)}}
    .ei-avatar{{width:32px;height:32px;border-radius:50%;display:grid;place-items:center;font-size:10px;font-weight:900;color:#06131d;background:linear-gradient(135deg,var(--eia-brand-cyan),var(--eia-brand-blue))}}
    .ei-context{{display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 15px;padding:0 2px}}
    .ei-breadcrumb{{font-size:11px;color:var(--eia-muted)}}
    .ei-breadcrumb b{{color:var(--eia-text)}}
    .ei-status{{font-size:10px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;padding:6px 9px;border-radius:999px;background:var(--eia-accentSoft);color:var(--eia-success);border:1px solid color-mix(in srgb,var(--eia-success) 25%,var(--eia-line))}}
    .ei-section-head{{display:flex;align-items:end;justify-content:space-between;gap:12px;margin:22px 0 10px}}
    .ei-section-title{{font-size:12px;font-weight:850;letter-spacing:.08em;text-transform:uppercase;color:var(--eia-text)}}
    .ei-section-sub{{font-size:11px;color:var(--eia-muted);margin-top:3px}}
    .ei-kpi-grid{{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px;margin:10px 0 18px}}
    .ei-kpi{{border:1px solid var(--eia-line);background:var(--eia-surface);border-radius:13px;padding:13px;min-height:86px}}
    .ei-kpi-label{{font-size:10px;text-transform:uppercase;letter-spacing:.06em;color:var(--eia-muted);font-weight:750}}
    .ei-kpi-value{{font-size:23px;font-weight:850;letter-spacing:-.02em;color:var(--eia-text);margin-top:5px}}
    .ei-kpi-note{{font-size:10px;color:var(--eia-muted);margin-top:4px}}
    .ei-lifecycle{{display:grid;grid-template-columns:repeat(11,minmax(82px,1fr));gap:5px;margin:8px 0 20px}}
    .ei-life{{position:relative;text-align:center;padding:9px 5px;border:1px solid var(--eia-line);border-radius:10px;background:var(--eia-surface);font-size:9px;color:var(--eia-muted)}}
    .ei-life .dot{{display:block;width:8px;height:8px;border-radius:50%;margin:0 auto 5px;background:var(--eia-subtle)}}
    .ei-life.done{{background:var(--eia-accentSoft);border-color:color-mix(in srgb,var(--eia-success) 35%,var(--eia-line));color:var(--eia-text)}}
    .ei-life.done .dot{{background:var(--eia-success)}}
    .ei-life.current{{border-color:var(--eia-accent);box-shadow:0 0 0 2px color-mix(in srgb,var(--eia-accent) 10%,transparent);color:var(--eia-text)}}
    .ei-life.current .dot{{background:var(--eia-accent)}}
    .ei-command-card{{border:1px solid var(--eia-line);border-radius:17px;padding:18px;background:linear-gradient(135deg,var(--eia-surface),color-mix(in srgb,var(--eia-accent2) 4%,var(--eia-surface)));box-shadow:0 10px 30px var(--eia-shadow)}}
    .ei-command-label{{font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:var(--eia-accent2);font-weight:850}}
    .ei-command-title{{font-size:21px;font-weight:850;color:var(--eia-text);margin-top:5px}}
    .ei-command-copy{{font-size:12px;color:var(--eia-muted);line-height:1.5;margin-top:6px}}
    .ei-nav-note{{font-size:10px;color:var(--eia-sidebarMuted);line-height:1.4;margin:-3px 4px 8px}}
    @media(max-width:1100px){{.ei-kpi-grid{{grid-template-columns:repeat(3,minmax(0,1fr))}}.ei-lifecycle{{grid-template-columns:repeat(6,minmax(80px,1fr))}}.ei-topbar-brand{{min-width:180px}}}}
    @media(max-width:700px){{.ei-topbar{{position:relative;top:auto}}.ei-search{{display:none}}.ei-kpi-grid{{grid-template-columns:repeat(2,minmax(0,1fr))}}.ei-lifecycle{{grid-template-columns:repeat(3,minmax(80px,1fr))}}.ei-pill{{display:none}}}}

    </style>
    """, unsafe_allow_html=True)
