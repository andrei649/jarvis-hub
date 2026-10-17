/* The question box. Enter sends and Shift+Enter starts a new line (an IME composition is never
   cut short); while an answer streams the send button becomes Stop. The 8 000-character cap is
   the server's (spec §7), counted here before the request is made. */
import React, { useId } from 'react';
import { useI18n } from '../../i18n';
import { Button, Icon } from '../../ui';

export const MAX_QUESTION = 8000;
const COUNTER_FROM = 7000;

export interface ComposerProps {
  value: string;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  phase: 'idle' | 'creating' | 'streaming';
  error: string | null;
  placeholder: string;
}

export function Composer({ value, onChange, onSubmit, onStop, phase, error, placeholder }: ComposerProps) {
  const { t } = useI18n();
  const id = `c${useId().replace(/:/g, '')}`;
  const over = value.length > MAX_QUESTION;
  const describedBy = [error ? `${id}-error` : null, `${id}-hint`].filter(Boolean).join(' ');
  return (
    <form
      className={['ws-composer', error && 'has-error'].filter(Boolean).join(' ')}
      onSubmit={(event) => { event.preventDefault(); onSubmit(); }}
      noValidate
    >
      {error && (
        <p className="ws-composer__error" id={`${id}-error`} role="alert">
          <Icon name="alert" size={14} /> <span>{error}</span>
        </p>
      )}
      <div className="ws-composer__box">
        <label htmlFor={id} className="ws-sr-only">{t('chat.composer.label')}</label>
        <textarea
          id={id} className="ws-composer__input" rows={2} value={value} placeholder={placeholder}
          aria-invalid={Boolean(error) || over || undefined} aria-describedby={describedBy}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => {
            if (event.key !== 'Enter' || event.shiftKey || event.nativeEvent.isComposing) return;
            event.preventDefault();
            if (phase === 'idle') onSubmit();
          }}
        />
        {phase === 'streaming'
          ? <Button variant="secondary" icon="stop" onClick={onStop}>{t('chat.composer.stop')}</Button>
          : <Button variant="primary" type="submit" icon="send" busy={phase === 'creating'} disabled={!value.trim()}>{t('chat.composer.send')}</Button>}
      </div>
      <p className="ws-composer__hint" id={`${id}-hint`}>
        <span>{t('chat.composer.hint')}</span>
        {value.length >= COUNTER_FROM && (
          <span className={['ws-counter', over && 'is-over'].filter(Boolean).join(' ')}>{t('common.charCount', { count: value.length, max: MAX_QUESTION })}</span>
        )}
      </p>
    </form>
  );
}
