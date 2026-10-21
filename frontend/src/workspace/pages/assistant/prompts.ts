/* Suggested first questions for the empty chat, chosen by the kind of department.

   Departments are free-form (an admin names them), so the kind is recognised from the slug and
   name with diacritics folded ("Vânzări" → "vanzari"); anything unrecognised gets questions that
   work for any team's documents. The questions themselves live in the dictionaries. */
import type { Department } from '../../api/types';
import type { MessageKey } from '../../i18n';

export type PromptGroup = 'general' | 'legal' | 'sales' | 'hr' | 'finance' | 'it';

const MATCHERS: [PromptGroup, RegExp][] = [
  ['legal', /juridic|legal|contract|avocat|conformitate|compliance/],
  ['sales', /vanzar|sales|comercial|marketing|clienti|customer/],
  ['hr', /resurse umane|resurse-umane|\bhr\b|personal|people|recrutare|talent/],
  ['finance', /financ|contab|finance|accounting|fiscal|buget|trezorerie/],
  ['it', /\bit\b|tehnic|tech|software|dezvoltare|infrastructur|helpdesk/],
];

const PROMPTS: Record<PromptGroup, MessageKey[]> = {
  general: ['prompts.general.1', 'prompts.general.2', 'prompts.general.3'],
  legal: ['prompts.legal.1', 'prompts.legal.2', 'prompts.legal.3'],
  sales: ['prompts.sales.1', 'prompts.sales.2', 'prompts.sales.3'],
  hr: ['prompts.hr.1', 'prompts.hr.2', 'prompts.hr.3'],
  finance: ['prompts.finance.1', 'prompts.finance.2', 'prompts.finance.3'],
  it: ['prompts.it.1', 'prompts.it.2', 'prompts.it.3'],
};

function fold(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

export function promptGroup(department: Pick<Department, 'slug' | 'name'>): PromptGroup {
  const haystack = `${fold(department.slug)} ${fold(department.name)}`;
  return MATCHERS.find(([, pattern]) => pattern.test(haystack))?.[0] ?? 'general';
}

export function suggestedPrompts(department: Pick<Department, 'slug' | 'name'>): MessageKey[] {
  return PROMPTS[promptGroup(department)];
}
