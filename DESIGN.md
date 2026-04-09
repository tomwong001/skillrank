# Design System — SkillRank

## Product Context
- **What this is:** A skill evaluation marketplace where AI skill authors submit their skills, get ranked via pairwise A/B eval with LLM judges, and developers/agents query the rankings.
- **Who it's for:** Skill authors (submit + get scored) and developers (browse rankings, integrate API).
- **Space/industry:** AI developer tools, eval/benchmark platforms. Peers: Chatbot Arena, HuggingFace Leaderboard, Langfuse.
- **Project type:** Web app / dashboard + API.

## Aesthetic Direction
- **Direction:** Industrial/Utilitarian with ambient depth. Function-first, data-dense, monospace accents on metrics. Not a marketing site. A serious tool with subtle visual polish.
- **Decoration level:** Intentional. Ambient glow orbs, dot-grid texture, card hover effects. Color is rare and meaningful. No gratuitous gradients or decorative blobs.
- **Mood:** Precise, trustworthy, alive. Like a Bloomberg Terminal that breathes. Dense data with subtle movement that makes it feel like a living system.
- **Reference sites:** Arena AI (lmarena.ai), HuggingFace Leaderboard, Langfuse.

## Typography
- **Display/Hero:** Satoshi 700/500 — geometric, confident, modern but not trendy. Available via Fontshare.
- **Body:** Geist 400/500/600 — Vercel's font, developers know it, excellent readability. Via Google Fonts.
- **UI/Labels:** Same as body (Geist).
- **Data/Tables:** Geist Mono 400/500 — tabular-nums for Elo scores, metrics, confidence intervals.
- **Code:** Geist Mono.
- **Loading:** Fontshare CDN (Satoshi) + Google Fonts CDN (Geist, Geist Mono). System font stack as fallback.
- **Scale:**
  - xs: 11px (mono labels, timestamps)
  - sm: 12px (secondary text, hints)
  - base: 14px (body)
  - md: 16px (card titles)
  - lg: 22px (section subtitles, scorecard name)
  - xl: 28px (section titles)
  - 2xl: 48px (hero title)

## Color
- **Approach:** Restrained with intentional accent depth. Two accent colors for gradient effects.
- **Background:** #0F1117 (deep navy-black, not pure black)
- **Surface 1:** #161926 (cards, nav)
- **Surface 2:** #1E2235 (nested surfaces, metric blocks)
- **Surface 3:** #282D44 (hover states)
- **Accent (primary):** #22D3EE (cyan, for rankings, scores, #1 glow)
- **Accent (secondary):** #818CF8 (indigo, for gradients paired with cyan)
- **Text primary:** #E8E8F0
- **Text secondary:** #9295AD
- **Text muted:** #5D6080
- **Border:** #2A2E45
- **Semantic:** success #34D399, warning #FBBF24, error #F87171, info #60A5FA
- **Accent dim:** rgba(34, 211, 238, 0.10) — badge backgrounds, row highlights
- **Accent glow:** rgba(34, 211, 238, 0.30) — text glow on #1 rank
- **Dark mode:** This IS the primary mode. Dark-first product.
- **Light mode strategy:** Invert surfaces to whites/grays. Accent shifts to deeper cyan #0891B2. Reduce glow intensity. Keep dot-grid at lower opacity.

### Light Mode Overrides
- Background: #F5F5F7
- Surface 1: #FFFFFF
- Surface 2: #F0F0F3
- Surface 3: #E5E5EA
- Text primary: #1A1A2E
- Text secondary: #6B6B80
- Text muted: #9999AA
- Accent: #0891B2
- Border: #D5D5DD

## Spacing
- **Base unit:** 4px
- **Density:** Comfortable (not cramped, not spacious)
- **Scale:** 2xs(2) xs(4) sm(8) md(16) lg(24) xl(32) 2xl(48) 3xl(64)

## Layout
- **Approach:** Grid-disciplined. Strict columns, predictable alignment.
- **Grid:** Single column for most content. Two-column for scorecard+terminal side-by-side.
- **Max content width:** 1200px
- **Border radius:**
  - sm: 4px (buttons, inputs, badges)
  - md: 8px (cards, tables, terminal)
  - lg: 12px (scorecard, modals)
  - full: 9999px (pills, badges)

## Motion
- **Approach:** Intentional. Ambient movement that makes the product feel alive, not decorative animation.
- **Ambient:** Slow-drifting glow orbs (20s cycle, ease-in-out), subtle dot-grid background.
- **Interactive:** Card hover glow (0.2s), table row highlight (0.15s), input focus ring (0.15s).
- **Functional:** Eval progress terminal with blinking cursor. Score loading transition.
- **Easing:** enter(ease-out) exit(ease-in) move(ease-in-out)
- **Duration:** micro(50-100ms) short(150-200ms) medium(250-300ms)
- **Nav:** Glassmorphism with backdrop-filter blur(16px), 80% opacity.

## Signature Elements
1. **Scorecard as trading card.** Glowing border on hover, cyan gradient top-bar, ambient radial light in corner. Designed for screenshotting and sharing.
2. **Eval terminal.** Real-time streaming output with colored status markers. Blinking cursor. Developers trust what they can see.
3. **Ambient background.** Slow-moving glow orbs (cyan + indigo) with dot-grid texture. The page breathes.
4. **Gradient text.** Hero title uses cyan-to-indigo gradient. Sparingly used, only for hero-level headlines.

## CSS Custom Properties
```css
:root {
  --bg: #0F1117;
  --surface-1: #161926;
  --surface-2: #1E2235;
  --surface-3: #282D44;
  --text-primary: #E8E8F0;
  --text-secondary: #9295AD;
  --text-muted: #5D6080;
  --accent: #22D3EE;
  --accent-2: #818CF8;
  --accent-dim: rgba(34, 211, 238, 0.10);
  --accent-glow: rgba(34, 211, 238, 0.30);
  --accent-2-dim: rgba(129, 140, 248, 0.10);
  --success: #34D399;
  --warning: #FBBF24;
  --error: #F87171;
  --info: #60A5FA;
  --border: #2A2E45;
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --font-display: 'Satoshi', system-ui, sans-serif;
  --font-body: 'Geist', system-ui, sans-serif;
  --font-mono: 'Geist Mono', 'SF Mono', monospace;
  --sp-2xs: 2px; --sp-xs: 4px; --sp-sm: 8px; --sp-md: 16px;
  --sp-lg: 24px; --sp-xl: 32px; --sp-2xl: 48px; --sp-3xl: 64px;
}
```

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-04-09 | Initial design system created | Created by /design-consultation. Industrial/utilitarian direction with ambient depth, based on competitive research of Arena AI, HuggingFace, Langfuse. |
| 2026-04-09 | Background lifted from pure black | User feedback: pure black (#0A0A0F) felt too dark. Moved to navy-black (#0F1117) with ambient glow orbs and dot-grid texture for visual interest. |
| 2026-04-09 | Added secondary accent (indigo) | Enables gradient effects (cyan-to-indigo) for hero text and scorecard top-bar. Adds warmth to the palette without breaking the restrained approach. |
| 2026-04-09 | Glassmorphism nav | Backdrop-filter blur on the sticky nav. Content shows through, creates depth when scrolling. |
