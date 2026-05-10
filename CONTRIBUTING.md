# Contributing to BACH

BACH is maintained as part of the ellmos project family. Contributions are welcome
but there's no guarantee of response time.

## Getting Started

1. Fork the repository
2. Clone: `git clone https://github.com/YOUR_USERNAME/bach.git`
3. Install: `pip install -r requirements.txt`
4. Initialize: `python system/setup.py`

## How to contribute

1. Create a feature branch (`git checkout -b feature/my-feature`)
2. Make your changes
3. Run tests (`bach test` or `python -m pytest`)
4. Commit with clear message
5. Open a Pull Request

### Good First Issues

Look for issues labeled [`good first issue`](https://github.com/ellmos-ai/bach/labels/good%20first%20issue) -- these are great starting points for new contributors.

## Guidelines

- Keep changes focused (one feature/fix per PR)
- Follow existing code style (Python, PEP8-ish)
- Add/update tests if applicable
- Update docs if behavior changes
- Don't break existing functionality

## What gets merged?

- Bug fixes: Almost always welcome
- New features: Open an Issue first to discuss
- Refactoring: Only if it clearly improves something
- New agents/skills: Very welcome as separate modules

## What won't get merged?

- Breaking changes without discussion
- Large refactors without prior agreement
- Features that add complexity without clear benefit
- Changes to CORE (dist_type=2) without good reason

---

> **BACH is a personal project.** It's maintained by one person in their free time.
> There's no support team, no SLA, no guaranteed response time.
> If you like it, use it. If you want to improve it, contribute.
> If it doesn't fit your needs, fork it and make it yours.
