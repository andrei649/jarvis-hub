/* Form controls. Every control is wired through FormField so the label, the hint and the error
   are programmatically tied to the input (`aria-describedby`, `aria-invalid`) — screen readers
   announce a server-mapped error exactly where the user is typing. */
import React, { forwardRef, useId } from 'react';
import { useI18n } from '../i18n';
import { Icon } from './icons';

export interface FieldIds {
  id: string;
  describedBy: string | undefined;
  invalid: boolean;
}

export interface FormFieldProps {
  label: React.ReactNode;
  hint?: React.ReactNode;
  error?: string | null;
  optional?: boolean;
  id?: string;
  className?: string;
  /** Rendered after the label on the same line (e.g. a character counter). */
  aside?: React.ReactNode;
  children: (ids: FieldIds) => React.ReactNode;
}

export function FormField({ label, hint, error, optional, id, className, aside, children }: FormFieldProps) {
  const { t } = useI18n();
  const auto = useId();
  const fieldId = id ?? `f${auto.replace(/:/g, '')}`;
  const hintId = hint ? `${fieldId}-hint` : undefined;
  const errorId = error ? `${fieldId}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(' ') || undefined;
  return (
    <div className={['ws-field', error && 'has-error', className].filter(Boolean).join(' ')}>
      <div className="ws-field__top">
        <label className="ws-field__label" htmlFor={fieldId}>
          {label}
          {optional && <span className="ws-field__optional"> {t('common.optional')}</span>}
        </label>
        {aside && <span className="ws-field__aside">{aside}</span>}
      </div>
      {children({ id: fieldId, describedBy, invalid: Boolean(error) })}
      {hint && <p className="ws-field__hint" id={hintId}>{hint}</p>}
      {error && (
        <p className="ws-field__error" id={errorId}>
          <Icon name="alert" size={14} /> <span>{error}</span>
        </p>
      )}
    </div>
  );
}

type FieldChrome = Pick<FormFieldProps, 'label' | 'hint' | 'error' | 'optional' | 'aside' | 'className'>;

export interface TextFieldProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'className'>, FieldChrome {
  inputClassName?: string;
}

export const TextField = forwardRef<HTMLInputElement, TextFieldProps>(function TextField(
  { label, hint, error, optional, aside, className, inputClassName, id, ...input },
  ref,
) {
  return (
    <FormField label={label} hint={hint} error={error} optional={optional} aside={aside} className={className} id={id}>
      {(ids) => (
        <input
          ref={ref}
          id={ids.id}
          className={['ws-input', inputClassName].filter(Boolean).join(' ')}
          aria-invalid={ids.invalid || undefined}
          aria-describedby={ids.describedBy}
          {...input}
        />
      )}
    </FormField>
  );
});

export interface TextAreaProps extends Omit<React.TextareaHTMLAttributes<HTMLTextAreaElement>, 'className'>, FieldChrome {}

export const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { label, hint, error, optional, aside, className, id, ...area },
  ref,
) {
  return (
    <FormField label={label} hint={hint} error={error} optional={optional} aside={aside} className={className} id={id}>
      {(ids) => (
        <textarea
          ref={ref}
          id={ids.id}
          className="ws-input ws-textarea"
          aria-invalid={ids.invalid || undefined}
          aria-describedby={ids.describedBy}
          {...area}
        />
      )}
    </FormField>
  );
});

export interface SelectOption { value: string; label: string; disabled?: boolean }

export interface SelectProps extends Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'className'>, FieldChrome {
  options: SelectOption[];
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(function Select(
  { label, hint, error, optional, aside, className, id, options, ...select },
  ref,
) {
  return (
    <FormField label={label} hint={hint} error={error} optional={optional} aside={aside} className={className} id={id}>
      {(ids) => (
        <div className="ws-select">
          <select
            ref={ref}
            id={ids.id}
            className="ws-input ws-select__control"
            aria-invalid={ids.invalid || undefined}
            aria-describedby={ids.describedBy}
            {...select}
          >
            {options.map((o) => <option key={o.value} value={o.value} disabled={o.disabled}>{o.label}</option>)}
          </select>
          <Icon name="chevronDown" size={16} className="ws-select__chevron" />
        </div>
      )}
    </FormField>
  );
});

export interface CheckboxProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type' | 'className'> {
  label: React.ReactNode;
  description?: React.ReactNode;
  className?: string;
}

export const Checkbox = forwardRef<HTMLInputElement, CheckboxProps>(function Checkbox(
  { label, description, className, id, ...input },
  ref,
) {
  const auto = useId();
  const boxId = id ?? `c${auto.replace(/:/g, '')}`;
  const descId = description ? `${boxId}-desc` : undefined;
  return (
    <div className={['ws-check', className].filter(Boolean).join(' ')}>
      <input ref={ref} id={boxId} type="checkbox" className="ws-check__box" aria-describedby={descId} {...input} />
      <div className="ws-check__text">
        <label htmlFor={boxId} className="ws-check__label">{label}</label>
        {description && <p id={descId} className="ws-check__desc">{description}</p>}
      </div>
    </div>
  );
});

export interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: React.ReactNode;
  description?: React.ReactNode;
  disabled?: boolean;
  id?: string;
}

/** A binary setting that applies immediately (no form submit), announced as a switch. */
export function Switch({ checked, onChange, label, description, disabled, id }: SwitchProps) {
  const auto = useId();
  const switchId = id ?? `s${auto.replace(/:/g, '')}`;
  const labelId = `${switchId}-label`;
  const descId = description ? `${switchId}-desc` : undefined;
  return (
    <div className="ws-switch-row">
      <div className="ws-switch-row__text">
        <span id={labelId} className="ws-switch-row__label">{label}</span>
        {description && <p id={descId} className="ws-check__desc">{description}</p>}
      </div>
      <button
        id={switchId}
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={labelId}
        aria-describedby={descId}
        disabled={disabled}
        className="ws-switch"
        onClick={() => onChange(!checked)}
      >
        <span className="ws-switch__thumb" aria-hidden="true" />
      </button>
    </div>
  );
}

export interface RadioCardOption<V extends string> {
  value: V;
  label: React.ReactNode;
  description?: React.ReactNode;
}

/** A radio group whose options carry an explanation (e.g. the model policy). */
export function RadioCards<V extends string>({ name, legend, value, options, onChange, disabled }: {
  name: string;
  legend: React.ReactNode;
  value: V;
  options: RadioCardOption<V>[];
  onChange: (value: V) => void;
  disabled?: boolean;
}) {
  const auto = useId().replace(/:/g, '');
  return (
    <fieldset className="ws-radio-cards" disabled={disabled}>
      <legend className="ws-field__label">{legend}</legend>
      {options.map((option) => {
        const optionId = `${name}-${option.value}-${auto}`;
        return (
          <label key={option.value} htmlFor={optionId} className={['ws-radio-card', value === option.value && 'is-selected'].filter(Boolean).join(' ')}>
            <input
              id={optionId} type="radio" name={name} value={option.value} checked={value === option.value}
              onChange={() => onChange(option.value)} aria-describedby={option.description ? `${optionId}-d` : undefined}
            />
            <span className="ws-radio-card__text">
              <span className="ws-radio-card__label">{option.label}</span>
              {option.description && <span id={`${optionId}-d`} className="ws-radio-card__desc">{option.description}</span>}
            </span>
          </label>
        );
      })}
    </fieldset>
  );
}
