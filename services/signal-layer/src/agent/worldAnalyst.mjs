import { scoreSignalsForWatchlist } from '../core/relevance.mjs';
import { buildWorldBriefFromSignals } from '../core/assessment.mjs';

export function createWorldAnalyst({ provider, getWatchlist }) {
  return {
    async answer({ question, mode = 'general', country, limit = 12 }) {
      const normalizedQuestion = String(question || '').toLowerCase();

      if (country || normalizedQuestion.includes('country') || normalizedQuestion.includes('romania') || normalizedQuestion.includes('uae')) {
        const iso2 = country || (normalizedQuestion.includes('uae') || normalizedQuestion.includes('emirates') ? 'AE' : 'RO');
        const assessment = await provider.fetchEntityAssessment({ type: 'country', id: iso2 });
        if (assessment.assessment) {
          return {
            type: 'world_analyst_answer',
            mode: 'country_assessment',
            question,
            answer: renderCountryAssessment(assessment.assessment),
            assessment: assessment.assessment,
            actionPolicy: 'approval_required_for_external_or_high_impact_actions'
          };
        }
      }

      const payload = await provider.fetchSignals({ limit: Math.max(limit, 50) });
      const scored = scoreSignalsForWatchlist(payload.signals, getWatchlist());
      const relevant = scored.filter(signal => signal.relevance.score > 0).slice(0, limit);
      const brief = buildWorldBriefFromSignals({
        signals: relevant.length ? relevant : scored.slice(0, limit),
        evidence: payload.evidence,
        provider: payload.provider,
        freshness: payload.freshness
      });

      return {
        type: 'world_analyst_answer',
        mode: inferMode(normalizedQuestion, mode),
        question,
        answer: renderBrief(brief),
        brief,
        signals: relevant,
        actionPolicy: 'approval_required_for_external_or_high_impact_actions'
      };
    }
  };
}

function inferMode(question, fallback) {
  if (question.includes('travel') || question.includes('flight') || question.includes('airport')) return 'travel_watch';
  if (question.includes('market') || question.includes('portfolio') || question.includes('bitcoin') || question.includes('crypto')) return 'market_pulse';
  if (question.includes('cyber') || question.includes('security') || question.includes('cve')) return 'cyber_pulse';
  if (question.includes('overnight') || question.includes('changed')) return 'overnight_brief';
  return fallback;
}

function renderBrief(brief) {
  const lines = [];
  lines.push(`${brief.title}: global status is ${brief.globalStatus}.`);
  lines.push(brief.executiveSummary);
  if (brief.topSignals?.length) {
    lines.push('Top relevant signals:');
    for (const signal of brief.topSignals.slice(0, 5)) {
      lines.push(`- ${signal.title} — ${signal.severity}, ${signal.confidence} confidence. ${signal.whyItMatters}`);
    }
  }
  if (brief.recommendations?.length) {
    lines.push('Recommended next actions:');
    for (const rec of brief.recommendations.slice(0, 4)) {
      lines.push(`- ${rec.label}${rec.requiresApproval ? ' Approval required.' : ''}`);
    }
  }
  const stale = brief.freshness?.stale ? 'some stale data present' : 'freshness acceptable';
  lines.push(`Source/freshness note: ${brief.sources?.length || brief.evidenceIds?.length || 0} evidence item(s), ${stale}.`);
  return lines.join('\n');
}

function renderCountryAssessment(assessment) {
  const lines = [];
  lines.push(`${assessment.subject.label} risk assessment: ${assessment.risk.level} (${assessment.risk.score}/100).`);
  lines.push(assessment.claim);
  if (assessment.drivers?.length) {
    lines.push('Main drivers:');
    for (const driver of assessment.drivers.slice(0, 5)) {
      if (typeof driver === 'string') lines.push(`- ${driver}`);
      else lines.push(`- ${driver.title || driver.type || 'Risk driver'} — ${driver.severity || 'unknown severity'}`);
    }
  }
  if (assessment.recommendations?.length) {
    lines.push('Recommended next actions:');
    for (const rec of assessment.recommendations.slice(0, 4)) {
      lines.push(`- ${typeof rec === 'string' ? rec : rec.label || JSON.stringify(rec)}`);
    }
  }
  const stale = assessment.freshness?.stale ? 'some stale data present' : 'freshness acceptable';
  lines.push(`Confidence: ${assessment.confidence}. Evidence items: ${assessment.evidenceIds?.length || 0}. Freshness: ${stale}.`);
  return lines.join('\n');
}
