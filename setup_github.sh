#!/bin/bash
# Run this script to initialize the git repo and push to GitHub.
# Usage: bash setup_github.sh YOUR_GITHUB_USERNAME

set -e
USERNAME=${1:-"YOUR_USERNAME"}
REPO="alphafO"

echo "Initializing git repo..."
git init
git add .
git commit -m "feat: initial AlphaFO project scaffold

- 8 F&O patterns: PCR divergence, OI buildup, max pain, IV crush,
  VWAP+OI, mean reversion, gap fill, expiry week theta
- FastAPI backend with async SQLAlchemy
- React + TailwindCSS frontend
- Backtesting engine with Sharpe/drawdown metrics
- Paper trading module with capital protection guardrails
- Docker Compose for local deployment
- Pattern plugin architecture for easy extension"

echo ""
echo "Now create the repo on GitHub:"
echo "  https://github.com/new — name it: $REPO"
echo ""
echo "Then run:"
echo "  git remote add origin https://github.com/$USERNAME/$REPO.git"
echo "  git branch -M main"
echo "  git push -u origin main"
