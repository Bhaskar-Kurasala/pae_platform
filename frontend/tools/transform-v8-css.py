"""Transform v8 inline CSS for use as a standalone Next.js stylesheet."""
import re
import sys
from pathlib import Path

src_path = Path(sys.argv[1])
dst_path = Path(sys.argv[2])

src = src_path.read_text(encoding="utf-8")

# Strip block comments first so braces inside comments don't confuse the brace walker.
src_no_comments = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)


def transform(css: str) -> str:
    """Walk CSS as `selector{body}` chunks (handling nested @media via recursion)."""
    out: list[str] = []
    i = 0
    n = len(css)
    while i < n:
        brace = css.find("{", i)
        if brace == -1:
            out.append(css[i:])
            break
        sel = css[i:brace]
        depth = 1
        j = brace + 1
        while j < n and depth > 0:
            ch = css[j]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
            j += 1
        body = css[brace + 1 : j - 1]
        sel_stripped = sel.strip()

        if sel_stripped.startswith("@media") or sel_stripped.startswith("@supports"):
            # Recurse into media body
            out.append(sel + "{" + transform(body) + "}")
        elif sel_stripped.startswith("@keyframes"):
            out.append(sel + "{" + body + "}")
        else:
            # Add `.dark` variant for any selector containing [data-theme="dark"]
            if '[data-theme="dark"]' in sel:
                parts = [p.strip() for p in sel.split(",")]
                new_parts: list[str] = []
                for p in parts:
                    new_parts.append(p)
                    if '[data-theme="dark"]' in p:
                        new_parts.append(p.replace('[data-theme="dark"]', ".dark"))
                sel = ",\n".join(new_parts)
            out.append(sel + "{" + body + "}")
        i = j
    return "".join(out)


final = transform(src_no_comments)

# Replace font CSS-var values to use the Next.js font variables.
final = final.replace(
    "--sans:'Inter',system-ui,sans-serif;",
    "--sans: var(--font-inter), 'Inter', system-ui, sans-serif;",
)
final = final.replace(
    "--serif:'Fraunces',Georgia,serif;",
    "--serif: var(--font-fraunces), 'Fraunces', Georgia, serif;",
)
final = final.replace(
    "--mono:'JetBrains Mono',monospace;",
    "--mono: var(--font-jetbrains-mono), 'JetBrains Mono', monospace;",
)

# Scope body-level rules to the portal shell so they don't fight Next.js root layout.
final = re.sub(
    r"html,body\{margin:0;height:100%;[^}]*\}",
    (
        ".v8-portal-shell{"
        "font-family:var(--sans);"
        "background:var(--bg-gradient), var(--bg);"
        "color:var(--ink);"
        "-webkit-font-smoothing:antialiased;"
        "transition:background .4s ease, color .4s ease"
        "}"
    ),
    final,
)
final = re.sub(r"\bbody\{overflow:hidden\}", ".v8-portal-shell{overflow:hidden}", final)
final = re.sub(r"\bbody\{overflow:auto\}", ".v8-portal-shell{overflow:auto}", final)

# Scope the floating orb pseudo-elements to the portal shell as well.
final = re.sub(r"body::before,\s*\nbody::after", ".v8-portal-shell::before,\n.v8-portal-shell::after", final)
final = re.sub(r"body::before\{", ".v8-portal-shell::before{", final)
final = re.sub(r"body::after\{", ".v8-portal-shell::after{", final)

header = (
    "/*\n"
    " * CareerForge v8 design system — extracted from uis/CareerForge_v8.html.\n"
    " * Canonical UI approved by the research/design team. Do not hand-edit;\n"
    " * regenerate via tools/transform-v8-css.py if the source changes.\n"
    " *\n"
    " * Transforms applied:\n"
    "  *   - [data-theme=\"dark\"] paired with .dark for next-themes\n"
    "  *   - body-level rules scoped to .v8-portal-shell\n"
    "  *   - font vars wired to Next.js font CSS variables\n"
    " */\n\n"
)

dst_path.write_text(header + final, encoding="utf-8")
print(f"Wrote {len(final)} chars to {dst_path}")
