/* Notifications: a bell with the unread count, a panel with the latest items, mark-read.

   The unread count is polled (cheap: one row) while the tab is visible; the list loads when the
   panel opens. Opening an item marks it read and follows its link when the link points inside
   the Workspace; "mark all read" clears the badge in one call. */
import React, { useCallback, useState } from 'react';
import { listNotifications, markNotificationsRead } from '../api/account';
import type { Notification } from '../api/types';
import { useErrorText } from '../app/errors';
import { usePolling } from '../app/hooks';
import { useI18n } from '../i18n';
import { appPathFromLink, navigate } from '../router';
import { Button, CountBadge, EmptyState, Icon, LoadingBlock, Popover, useToast } from '../ui';

const POLL_MS = 60_000;
const LIST_LIMIT = 20;

export function NotificationsMenu() {
  const { t, tn, fmt } = useI18n();
  const toast = useToast();
  const errorText = useErrorText();
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<Notification[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [markingAll, setMarkingAll] = useState(false);

  const pollCount = useCallback(async () => {
    try {
      setUnread((await listNotifications({ unread: true, limit: 1 })).unread_count);
    } catch {
      // Keep the last count; the bell is advisory and the next poll retries.
    }
  }, []);
  usePolling(pollCount, POLL_MS);

  const loadList = useCallback(async () => {
    setListError(null);
    try {
      const data = await listNotifications({ limit: LIST_LIMIT });
      setItems(data.items);
      setUnread(data.unread_count);
    } catch (err) {
      setListError(errorText(err));
    }
  }, [errorText]);

  const open = async (item: Notification, close: () => void) => {
    const target = appPathFromLink(item.link);
    if (!item.read_at) {
      try {
        const { unread_count } = await markNotificationsRead({ ids: [item.id] });
        setUnread(unread_count);
        setItems((list) => list?.map((x) => (x.id === item.id ? { ...x, read_at: Date.now() / 1000 } : x)) ?? null);
      } catch (err) {
        toast.error(errorText(err));
      }
    }
    if (target) { close(); navigate(target); }
  };

  const markAll = async () => {
    setMarkingAll(true);
    try {
      const { unread_count } = await markNotificationsRead({ all: true });
      setUnread(unread_count);
      const now = Date.now() / 1000;
      setItems((list) => list?.map((x) => (x.read_at ? x : { ...x, read_at: now })) ?? null);
    } catch (err) {
      toast.error(errorText(err));
    } finally {
      setMarkingAll(false);
    }
  };

  const badgeLabel = tn('notifications.unread', unread);
  return (
    <Popover
      label={t('notifications.title')}
      onOpenChange={(isOpen) => { if (isOpen) void loadList(); }}
      trigger={(props) => (
        <button type="button" className="ws-icon-btn ws-icon-btn--ghost ws-icon-btn--md ws-bell" {...props}
          aria-label={unread > 0 ? `${t('notifications.title')} — ${badgeLabel}` : t('notifications.title')} title={t('notifications.title')}>
          <Icon name="bell" />
          <CountBadge count={unread} label={badgeLabel} />
        </button>
      )}
    >
      {(close) => (
        <div className="ws-notif">
          <div className="ws-notif__head">
            <p className="ws-popover__title">{t('notifications.title')}</p>
            <Button size="sm" variant="ghost" onClick={markAll} busy={markingAll} disabled={unread === 0}>{t('notifications.markAll')}</Button>
          </div>
          {listError && (
            <div className="ws-notif__state">
              <p className="ws-inline-error" role="alert">{listError}</p>
              <Button size="sm" icon="refresh" onClick={() => void loadList()}>{t('common.retry')}</Button>
            </div>
          )}
          {!listError && items === null && <LoadingBlock label={t('common.loading')} lines={3} />}
          {!listError && items?.length === 0 && (
            <EmptyState compact icon="bell" title={t('notifications.empty')} body={t('notifications.emptyBody')} />
          )}
          {!listError && items && items.length > 0 && (
            <ul className="ws-notif__list">
              {items.map((item) => (
                <li key={item.id}>
                  <button type="button" className={['ws-notif__item', !item.read_at && 'is-unread'].filter(Boolean).join(' ')} onClick={() => void open(item, close)}>
                    <span className="ws-notif__dot" aria-hidden="true" />
                    <span className="ws-notif__text">
                      <span className="ws-notif__title">
                        {!item.read_at && <span className="ws-sr-only">{t('notifications.unreadMarker')} </span>}
                        {item.title}
                      </span>
                      {item.body && <span className="ws-notif__body">{item.body}</span>}
                      <time className="ws-notif__time" dateTime={new Date(item.created_at * 1000).toISOString()}>{fmt.relative(item.created_at)}</time>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </Popover>
  );
}
