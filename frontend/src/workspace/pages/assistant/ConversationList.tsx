/* The conversations of the current department: newest first, filtered by title as you type,
   each a real link with a menu to rename or delete it. The same component renders inline on
   wide screens and inside a drawer on narrow ones. */
import React, { useMemo } from 'react';
import type { ConversationSummary } from '../../api/types';
import { describeError } from '../../app/errors';
import { useI18n } from '../../i18n';
import { Link } from '../../router';
import { Button, EmptyState, IconButton, LoadingBlock, Menu, Notice, TextField } from '../../ui';

export interface ConversationListProps {
  conversations: ConversationSummary[] | null;
  loading: boolean;
  error: unknown;
  activeId: number | null;
  search: string;
  onSearch: (value: string) => void;
  onNew: () => void;
  onRetry: () => void;
  onRename: (conversation: ConversationSummary) => void;
  onDelete: (conversation: ConversationSummary) => void;
  onNavigate?: () => void;
}

export function ConversationList(props: ConversationListProps) {
  const { conversations, loading, error, activeId, search, onSearch, onNew, onRetry, onRename, onDelete, onNavigate } = props;
  const i18n = useI18n();
  const { t, tn, fmt } = i18n;
  const visible = useMemo(() => {
    const needle = search.trim().toLocaleLowerCase();
    const sorted = [...(conversations ?? [])].sort((a, b) => b.updated_at - a.updated_at);
    return needle ? sorted.filter((c) => c.title.toLocaleLowerCase().includes(needle)) : sorted;
  }, [conversations, search]);

  return (
    <nav className="ws-convs" aria-label={t('assistant.list.label')}>
      <div className="ws-convs__top">
        <Button variant="primary" icon="plus" block onClick={onNew}>{t('assistant.list.new')}</Button>
        <TextField
          label={t('assistant.list.search')} type="search" value={search} onChange={(e) => onSearch(e.target.value)}
          placeholder={t('assistant.list.searchPlaceholder')}
        />
      </div>
      {error ? (
        <Notice tone="danger" live="assertive" action={<Button size="sm" icon="refresh" onClick={onRetry}>{t('common.retry')}</Button>}>
          {describeError(i18n, error)}
        </Notice>
      ) : null}
      {!error && loading && !conversations && <LoadingBlock label={t('common.loading')} lines={4} />}
      {!error && conversations && conversations.length === 0 && (
        <EmptyState compact icon="chat" title={t('assistant.list.empty')} body={t('assistant.list.emptyBody')} />
      )}
      {!error && conversations && conversations.length > 0 && visible.length === 0 && (
        <p className="ws-muted ws-small ws-convs__none">{t('assistant.list.noMatch')}</p>
      )}
      {visible.length > 0 && (
        <ul className="ws-convs__list">
          {visible.map((c) => {
            const active = c.id === activeId;
            return (
              <li key={c.id} className={['ws-conv', active && 'is-active'].filter(Boolean).join(' ')}>
                <Link to={`/assistant/${c.id}`} className="ws-conv__link" aria-current={active ? 'page' : undefined} onClick={onNavigate}>
                  <span className="ws-conv__title">{c.title}</span>
                  <span className="ws-conv__meta">
                    <time dateTime={new Date(c.updated_at * 1000).toISOString()}>{fmt.relative(c.updated_at)}</time>
                    {' · '}
                    {tn('assistant.list.messages', c.message_count ?? 0)}
                  </span>
                </Link>
                <Menu
                  label={t('assistant.list.actionsFor', { title: c.title })}
                  items={[
                    { id: 'rename', label: t('assistant.action.rename'), icon: 'edit', onSelect: () => onRename(c) },
                    { id: 'delete', label: t('assistant.action.delete'), icon: 'trash', danger: true, onSelect: () => onDelete(c) },
                  ]}
                  trigger={(trigger) => <IconButton size="sm" icon="more" label={t('assistant.list.actionsFor', { title: c.title })} {...trigger} />}
                />
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
