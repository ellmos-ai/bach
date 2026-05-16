# -*- coding: utf-8 -*-
# SPDX-License-Identifier: MIT
"""
Copyright (c) 2026 BACH Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

"""
FinancialProof - Web Research Agent
Sammelt Informationen aus verschiedenen Web-Quellen
"""
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict, Any, List, Optional
import re

from ..base import (
    BaseAnalyzer, AnalysisResult, AnalysisParameters,
    AnalysisCategory, AnalysisTimeframe
)
from ..registry import AnalysisRegistry


@AnalysisRegistry.register
class ResearchAgent(BaseAnalyzer):
    """Web Research Agent für umfassende Asset-Recherche."""

    name = "research_agent"
    display_name = "Web-Recherche Agent"
    category = AnalysisCategory.RESEARCH
    description = "Sammelt umfassende Informationen aus Web-Quellen"
    estimated_duration = 30
    min_data_points = 1

    supported_timeframes = [AnalysisTimeframe.SHORT, AnalysisTimeframe.MEDIUM]

    @classmethod
    def get_parameter_schema(cls) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_fundamentals": {"type": "boolean", "default": True},
                "include_recommendations": {"type": "boolean", "default": True},
                "include_news": {"type": "boolean", "default": True},
                "research_topic": {"type": "string", "default": ""}
            }
        }

    async def analyze(self, params: AnalysisParameters) -> AnalysisResult:
        symbol = params.symbol
        self.set_progress(5)

        try:
            import yfinance as yf
            ticker = yf.Ticker(symbol)
            research_data = {}
            sections = []

            if params.custom_params.get('include_fundamentals', True):
                self.set_progress(20)
                fundamentals = self._get_fundamentals(ticker)
                research_data['fundamentals'] = fundamentals
                sections.append(('fundamentals', fundamentals))

            if params.custom_params.get('include_recommendations', True):
                self.set_progress(40)
                recommendations = self._get_recommendations(ticker)
                research_data['recommendations'] = recommendations
                sections.append(('recommendations', recommendations))

            if params.custom_params.get('include_news', True):
                self.set_progress(60)
                news = self._get_news_summary(ticker)
                research_data['news'] = news
                sections.append(('news', news))

            self.set_progress(75)
            dividends = self._get_dividend_info(ticker)
            research_data['dividends'] = dividends

            self.set_progress(90)
            result = self._build_result(symbol, research_data, sections)
            self.set_progress(100)
            return result

        except Exception as e:
            return self.create_empty_result(self.name, symbol, str(e))

    def _get_fundamentals(self, ticker) -> Dict:
        try:
            info = ticker.info
            return {
                'company_name': info.get('longName', 'N/A'),
                'sector': info.get('sector', 'N/A'),
                'industry': info.get('industry', 'N/A'),
                'market_cap': info.get('marketCap', 0),
                'market_cap_formatted': self._format_large_number(info.get('marketCap', 0)),
                'pe_ratio': info.get('trailingPE', 'N/A'),
                'forward_pe': info.get('forwardPE', 'N/A'),
                'current_price': info.get('currentPrice', info.get('regularMarketPrice', 'N/A')),
                'target_price': info.get('targetMeanPrice', 'N/A'),
                'dividend_yield': info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0,
                'description': info.get('longBusinessSummary', '')[:500] if info.get('longBusinessSummary') else 'N/A'
            }
        except Exception as e:
            return {'error': str(e)}

    def _get_recommendations(self, ticker) -> Dict:
        try:
            rec = ticker.recommendations
            if rec is None or rec.empty:
                return {'available': False}
            recent = rec.tail(10)
            grades = recent['To Grade'].value_counts().to_dict() if 'To Grade' in recent.columns else {}
            buy_grades = ['Buy', 'Strong Buy', 'Overweight', 'Outperform']
            sell_grades = ['Sell', 'Strong Sell', 'Underweight', 'Underperform']
            buy_count = sum(grades.get(g, 0) for g in buy_grades)
            sell_count = sum(grades.get(g, 0) for g in sell_grades)
            hold_count = sum(grades.get(g, 0) for g in ['Hold', 'Neutral', 'Market Perform'])
            total = buy_count + sell_count + hold_count
            consensus = 'buy' if buy_count > sell_count + hold_count else \
                       'sell' if sell_count > buy_count + hold_count else 'hold' if total > 0 else 'unknown'
            return {
                'available': True, 'total_recommendations': total,
                'buy_count': buy_count, 'hold_count': hold_count, 'sell_count': sell_count,
                'consensus': consensus, 'grade_distribution': grades
            }
        except Exception as e:
            return {'available': False, 'error': str(e)}

    def _get_news_summary(self, ticker) -> Dict:
        try:
            news = ticker.news
            if not news:
                return {'available': False}
            articles = [{'title': item.get('title', ''), 'publisher': item.get('publisher', '')} for item in news[:10]]
            return {'available': True, 'total_articles': len(news), 'recent_articles': articles}
        except Exception as e:
            return {'available': False, 'error': str(e)}

    def _get_dividend_info(self, ticker) -> Dict:
        try:
            info = ticker.info
            return {
                'pays_dividend': info.get('dividendYield', 0) > 0,
                'dividend_yield': info.get('dividendYield', 0) * 100 if info.get('dividendYield') else 0,
                'dividend_rate': info.get('dividendRate', 'N/A')
            }
        except Exception as e:
            return {'error': str(e)}

    def _format_large_number(self, num) -> str:
        if not num or num == 'N/A':
            return 'N/A'
        try:
            num = float(num)
            if num >= 1e12: return f"{num/1e12:.2f}T"
            elif num >= 1e9: return f"{num/1e9:.2f}B"
            elif num >= 1e6: return f"{num/1e6:.2f}M"
            return f"{num:.2f}"
        except (ValueError, TypeError):
            return str(num)

    def _build_result(self, symbol: str, research_data: Dict, sections: List) -> AnalysisResult:
        signals = []
        fundamentals = research_data.get('fundamentals', {})
        if fundamentals.get('pe_ratio') and fundamentals.get('pe_ratio') != 'N/A':
            pe = fundamentals['pe_ratio']
            if pe < 15: signals.append(('fundamental', 'buy', 'Niedriges KGV'))
            elif pe > 30: signals.append(('fundamental', 'sell', 'Hohes KGV'))

        current = fundamentals.get('current_price', 0)
        target = fundamentals.get('target_price', 0)
        if current and target and current != 'N/A' and target != 'N/A':
            upside = ((target - current) / current) * 100
            if upside > 15: signals.append(('analyst', 'buy', f'Kursziel +{upside:.1f}%'))
            elif upside < -10: signals.append(('analyst', 'sell', f'Kursziel {upside:.1f}%'))

        rec_data = research_data.get('recommendations', {})
        if rec_data.get('available') and rec_data.get('consensus'):
            signals.append(('consensus', rec_data['consensus'], f"Analysten-Konsens: {rec_data['consensus']}"))

        buy_signals = sum(1 for s in signals if s[1] == 'buy')
        sell_signals = sum(1 for s in signals if s[1] == 'sell')
        if buy_signals > sell_signals:
            overall_recommendation, confidence = 'buy', 0.5 + (buy_signals - sell_signals) * 0.1
        elif sell_signals > buy_signals:
            overall_recommendation, confidence = 'sell', 0.5 + (sell_signals - buy_signals) * 0.1
        else:
            overall_recommendation, confidence = 'hold', 0.5
        confidence = min(0.8, confidence)

        company = fundamentals.get('company_name', symbol)
        summary = f"Recherche-Bericht für {company} ({symbol}). Gesamteinschätzung: {overall_recommendation.upper()}."

        return AnalysisResult(
            analysis_type=self.name, symbol=symbol, timestamp=datetime.now(),
            summary=summary, confidence=confidence,
            data={'company_name': company, 'fundamentals': fundamentals, 'recommendations': rec_data},
            signals=[{'type': overall_recommendation, 'indicator': 'Research Agent', 'confidence': confidence}],
            recommendation=overall_recommendation
        )
