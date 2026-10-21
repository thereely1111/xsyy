import { useMemo } from 'react';
import { useAppStore } from '../store/appStore';
import { API_BASE } from '../lib/api';

function formatTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const now = Date.now();
  const diffMin = Math.floor((now - date.getTime()) / 60000);
  if (diffMin < 1) return '刚刚';
  if (diffMin < 60) return `${diffMin} 分钟前`;
  const diffHour = Math.floor(diffMin / 60);
  if (diffHour < 24) return `${diffHour} 小时前`;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
}

function resolveImageUrl(url: string | null): string | null {
  if (!url) return null;
  return url.startsWith('/') ? `${API_BASE}${url}` : url;
}

export function SystemMessagesModal() {
  const open = useAppStore((s) => s.systemMessagesOpen);
  const messages = useAppStore((s) => s.systemMessages);
  const closeSystemMessages = useAppStore((s) => s.closeSystemMessages);
  const markSystemMessageRead = useAppStore((s) => s.markSystemMessageRead);
  const clearSystemMessages = useAppStore((s) => s.clearSystemMessages);
  const announcements = useAppStore((s) => s.announcements);
  const ackedAnnouncementIds = useAppStore((s) => s.ackedAnnouncementIds);
  const ackAnnouncement = useAppStore((s) => s.ackAnnouncement);

  const sortedMessages = useMemo(() => {
    return [...messages].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());
  }, [messages]);

  const sortedAnnouncements = useMemo(() => {
    return [...announcements].sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );
  }, [announcements]);

  if (!open) return null;

  const isEmpty = sortedMessages.length === 0 && sortedAnnouncements.length === 0;

  return (
    <div className="fixed inset-0 z-[1400] flex items-center justify-center bg-black/55 p-4">
      <div className="w-full max-w-2xl rounded-2xl border border-zheshi/35 bg-[#f7f0e2f5] p-6 shadow-neo backdrop-blur">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-serifCn text-2xl font-black text-daiblue">系统消息</h3>
          <div className="flex items-center gap-2">
            <button type="button" onClick={clearSystemMessages} className="rounded-lg border border-cinnabar/40 px-3 py-1.5 text-sm text-cinnabar transition hover:bg-cinnabar/10">清空消息</button>
            <button type="button" onClick={closeSystemMessages} className="rounded-lg border border-daiblue/30 px-3 py-1.5 text-sm text-daiblue transition hover:bg-white/70">关闭</button>
          </div>
        </div>
        <div className="max-h-[60vh] space-y-4 overflow-y-auto rounded-xl border border-daiblue/15 bg-white/75 p-4">
          {isEmpty ? <p className="py-8 text-center text-sm text-zheshi">暂无消息</p> : <>
            {sortedMessages.length > 0 && <section><h4 className="mb-2 text-xs font-semibold tracking-wide text-zheshi">系统通知</h4><div className="space-y-3">{sortedMessages.map((item) => <button key={item.id} type="button" onClick={() => markSystemMessageRead(item.id)} className={`w-full rounded-lg border px-4 py-3 text-left transition ${item.read ? 'border-daiblue/15 bg-white/70 text-ink' : 'border-cinnabar/30 bg-[#fff6ef] text-ink shadow-sm'}`}><p className="text-sm leading-6">{item.content}</p><div className="mt-2 flex items-center justify-between text-xs text-zheshi"><span>{formatTime(item.createdAt)}</span><span>{item.read ? '已读' : '未读'}</span></div></button>)}</div></section>}
            {sortedAnnouncements.length > 0 && <section><h4 className="mb-2 text-xs font-semibold tracking-wide text-zheshi">公告</h4><div className="space-y-3">{sortedAnnouncements.map((item) => { const unread = !ackedAnnouncementIds.includes(String(item.id)); const imgSrc = resolveImageUrl(item.imageUrl); return <button key={item.id} type="button" onClick={() => ackAnnouncement(item.id)} className={`w-full rounded-lg border px-4 py-3 text-left transition ${unread ? 'border-cinnabar/30 bg-[#fff6ef] text-ink shadow-sm' : 'border-daiblue/15 bg-white/70 text-ink'}`}>{item.title ? <p className="mb-1 text-sm font-bold text-daiblue">{item.title}</p> : null}{imgSrc ? <img src={imgSrc} alt={item.title || '公告配图'} className="mb-2 max-h-48 w-full rounded-lg object-cover" /> : null}<p className="whitespace-pre-wrap text-sm leading-6">{item.content}</p><div className="mt-2 flex items-center justify-between text-xs text-zheshi"><span>{formatTime(item.createdAt)}</span><span>{unread ? '未读' : '已读'}</span></div></button>; })}</div></section>}
          </>}
        </div>
      </div>
    </div>
  );
}
