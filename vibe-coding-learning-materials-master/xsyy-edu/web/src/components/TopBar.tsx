import { useEffect, useState } from 'react';
import { useAppStore } from '../store/appStore';

export function TopBar() {
  const currentUser = useAppStore((s) => s.currentUser);
  const quota = useAppStore((s) => s.quota);
  const openAuthModal = useAppStore((s) => s.openAuthModal);
  const openAccountCenter = useAppStore((s) => s.openAccountCenter);
  const openSystemMessages = useAppStore((s) => s.openSystemMessages);
  const openFeedbackModal = useAppStore((s) => s.openFeedbackModal);
  const logout = useAppStore((s) => s.logout);
  const refreshQuota = useAppStore((s) => s.refreshQuota);

  // 系统消息 / 公告 未读红点
  const systemMessages = useAppStore((s) => s.systemMessages);
  const announcements = useAppStore((s) => s.announcements);
  const ackedAnnouncementIds = useAppStore((s) => s.ackedAnnouncementIds);
  const hasUnreadSystem = systemMessages.some((m) => !m.read);
  const hasUnreadAnnouncement = announcements.some(
    (a) => !ackedAnnouncementIds.includes(String(a.id)),
  );
  const hasUnreadMessage = hasUnreadSystem || hasUnreadAnnouncement;

  const [menuOpen, setMenuOpen] = useState(false);

  const inviteInfo = useAppStore((s) => s.inviteInfo);
  const welfarePolicy = useAppStore((s) => s.welfarePolicy);
  const inviteRewardQuota = inviteInfo?.inviteRewardQuota ?? welfarePolicy?.inviteRewardQuota ?? 5;
  const newUserGiftQuota = inviteInfo?.newUserGiftQuota ?? welfarePolicy?.newUserGiftQuota ?? 8;
  const subscriptionPlan = quota?.subscription?.plan;
  const isMember = Boolean(currentUser && quota?.subscription);
  const memberTier = subscriptionPlan === 'monthly'
    ? '铜标'
    : subscriptionPlan === 'quarterly'
      ? '银标'
      : '金标';
  const inviteBubbleText = !currentUser
    ? `新用户注册即送 ${newUserGiftQuota} 次免费生成 · 邀好友双方各得 ${inviteRewardQuota} 次`
    : isMember
      ? '会员有效期内无限生成 · 邀好友下单最高返利60元'
      : `你还剩 ${quota?.remainingTotal ?? 0} 次生成额度 · 邀 1 位好友 +${inviteRewardQuota} 次`;
  const inviteTarget = isMember ? 'user_interface.html#commission' : 'user_interface.html#recharge';

  const displayName = currentUser?.username || '用户';
  const avatarChar = (() => {
    const firstChar = displayName.charAt(0);
    return /[a-zA-Z0-9]/.test(firstChar) ? firstChar.toUpperCase() : firstChar || '用';
  })();
  const avatarPalette = ['#3E5C76', '#B83B43', '#7D9F88', '#D9A441', '#8B6F47', '#6B8E9F', '#A67C52', '#9B7A6B'];
  const avatarBackground = avatarPalette[(displayName.charCodeAt(0) || 0) % avatarPalette.length];

  useEffect(() => {
    const handlePointerDown = (event: PointerEvent) => {
      const menuElement = document.getElementById('topbar-user-menu');
      if (menuElement && !menuElement.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    };

    document.addEventListener('pointerdown', handlePointerDown);
    return () => document.removeEventListener('pointerdown', handlePointerDown);
  }, []);

  // 定期刷新额度（每30秒）
  useEffect(() => {
    if (!currentUser) return;

    const intervalId = setInterval(() => {
      void refreshQuota();
    }, 30000);

    return () => clearInterval(intervalId);
  }, [currentUser, refreshQuota]);

  return (
    <header className="sticky top-0 z-50 border-b border-daiblue/15 bg-[#f3efe6cc] px-4 py-3 backdrop-blur md:px-8">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
        <div className="flex min-w-0 items-center gap-3">
          <img src="/xsyy-logo.webp" alt="象数演易" className="h-11 w-11 shrink-0 rounded-full border border-daiblue/25" />
          <div className="min-w-0">
            <div className="flex items-center gap-3">
              <p className="whitespace-nowrap font-sans text-xl font-black tracking-[0.14em] text-daiblue">象数演易</p>
              {isMember ? (
                <button
                  onClick={() => { window.location.href = 'user_interface.html#recharge'; }}
                  className="inline-flex shrink-0 items-center gap-1.5 rounded-full border-2 border-[#e6a23c]/60 bg-gradient-to-b from-[#fdf6ec] to-[#f5e6c8] px-3 py-1.5 font-sans text-xs font-bold text-daiblue shadow-neo transition hover:border-[#e6a23c] hover:shadow-md"
                  title="点击进入额度管理"
                >
                  <span className="text-xs opacity-80">{memberTier}</span>
                  <span className="text-base font-black text-[#e67e22]">∞</span>
                </button>
              ) : (
                <button
                  onClick={() => { window.location.href = 'user_interface.html#recharge'; }}
                  className="shrink-0 rounded-full border border-cinnabar/50 bg-cinnabar px-3 py-1.5 font-sans text-xs font-bold text-white shadow-neo transition hover:brightness-95"
                  title="点击进入额度管理"
                >
                  去充值
                </button>
              )}
            </div>
            <p className="text-xs tracking-[0.18em] text-zheshi">Neo-Chinese Intelligence</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => { window.location.href = inviteTarget; }}
            className="group relative hidden max-w-[360px] rounded-2xl border border-[#d9a441]/45 bg-[#fffaf0]/90 px-4 py-2 text-left shadow-neo transition hover:border-[#b88320] hover:bg-white md:block"
            title="点击查看邀请有礼"
          >
            <span className="absolute -bottom-1 left-7 h-2 w-2 rotate-45 border-b border-r border-[#d9a441]/45 bg-[#fffaf0] transition group-hover:bg-white" />
            <span className="block font-sans text-sm font-bold text-cinnabar">邀请有礼</span>
            <span className="mt-0.5 block whitespace-nowrap text-xs text-zheshi">{inviteBubbleText}</span>
          </button>

          {!currentUser ? (
            <button
              onClick={openAuthModal}
              className="relative rounded-full border-2 border-daiblue bg-gradient-to-b from-[#fffdf8cc] to-[#e8e1d2cc] px-5 py-2 font-sans text-base font-bold text-daiblue shadow-neo transition hover:border-ink hover:from-[#f9f4e8] hover:to-[#dfd3bd]"
            >
              登入
            </button>
          ) : (
            <>
              <button
                onClick={() => { window.location.href = inviteTarget; }}
                className="rounded-full border border-[#d9a441]/50 bg-[#fff8e9] px-3 py-2 font-sans text-sm font-bold text-cinnabar shadow-neo transition hover:brightness-95 md:hidden"
                title={inviteBubbleText}
              >
                邀请
              </button>

              <div className="relative" id="topbar-user-menu">
                <button
                  type="button"
                  onClick={() => setMenuOpen((prev) => !prev)}
                  className="inline-flex items-center gap-2 rounded-full border border-daiblue/30 bg-white/80 px-3 py-2 text-sm font-semibold text-daiblue transition hover:bg-white"
                  aria-haspopup="menu"
                  aria-expanded={menuOpen}
                >
                  <span className="flex h-9 w-9 items-center justify-center rounded-full border-2 border-white text-base font-bold text-white shadow-neo" style={{ backgroundColor: avatarBackground }}>
                    {avatarChar}
                  </span>
                  <span className="max-w-32 truncate font-sans text-base font-bold tracking-[0.04em] text-daiblue">
                    {displayName}
                  </span>
                </button>

                {menuOpen ? (
                  <div className="absolute right-0 top-11 z-30 w-40 rounded-xl border border-daiblue/20 bg-[#fffaf1f2] p-1.5 shadow-neo">
                    <button
                      type="button"
                      onClick={() => {
                        setMenuOpen(false);
                        openAccountCenter();
                      }}
                      className="w-full rounded-lg px-3 py-2 text-left text-sm text-ink transition hover:bg-[#f3ebdc]"
                    >
                      个人中心
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setMenuOpen(false);
                        openSystemMessages();
                      }}
                      className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-ink transition hover:bg-[#f3ebdc]"
                    >
                      <span>系统消息</span>
                      {hasUnreadMessage ? (
                        <span className="inline-block h-2 w-2 rounded-full bg-cinnabar" aria-label="有未读消息" />
                      ) : null}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setMenuOpen(false);
                        openFeedbackModal();
                      }}
                      className="w-full rounded-lg px-3 py-2 text-left text-sm text-ink transition hover:bg-[#f3ebdc]"
                    >
                      问题反馈
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setMenuOpen(false);
                        logout();
                      }}
                      className="w-full rounded-lg px-3 py-2 text-left text-sm text-cinnabar transition hover:bg-[#f9e9e5]"
                    >
                      退出登录
                    </button>
                  </div>
                ) : null}
              </div>
            </>
          )}
        </div>
      </div>
    </header>
  );
}
