import { useAppStore } from '../store/appStore';

export function InviteModal() {
  const open = useAppStore((s) => s.inviteModalOpen);
  const inviteInfo = useAppStore((s) => s.inviteInfo);
  const authToken = useAppStore((s) => s.authToken);
  const closeInviteModal = useAppStore((s) => s.closeInviteModal);
  const addToast = useAppStore((s) => s.addToast);

  if (!open || !inviteInfo || !authToken) {
    return null;
  }

  const rewardQuota = inviteInfo.inviteRewardQuota || 3;
  const invitedCount = inviteInfo.invitedCount || 0;

  const copyInviteCode = async () => {
    try {
      await navigator.clipboard.writeText(inviteInfo.inviteCode);
      addToast('邀请码已复制', 'success');
    } catch {
      addToast('复制失败，请手动复制', 'error');
    }
  };

  return (
    <div className="fixed inset-0 z-[1100] flex items-center justify-center bg-black/50 p-4">
      <div className="max-h-[92vh] w-full max-w-4xl overflow-y-auto rounded-lg border border-zheshi/30 bg-[#f9f5ebf2] p-6 shadow-neo backdrop-blur">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div>
            <h2 className="font-serifCn text-2xl font-black text-daiblue">邀请有礼</h2>
            <p className="text-sm text-zheshi">邀请好友注册并购买会员，你（直接邀请人）可得单级返佣；每成功邀请 1 人另赠固定额度，邀满里程碑再领奖励。</p>
          </div>
          <button onClick={closeInviteModal} className="rounded-md border border-daiblue/30 px-3 py-1 text-sm text-daiblue transition hover:bg-daiblue/10 active:scale-95">
            关闭
          </button>
        </div>

        <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-daiblue/20 bg-white/70 px-4 py-3">
          <span className="text-sm text-zheshi">专属邀请码</span>
          <strong className="font-mono text-lg tracking-[0.12em] text-daiblue">{inviteInfo.inviteCode}</strong>
          <button onClick={() => void copyInviteCode()} className="rounded-md border border-daiblue/30 px-3 py-1 text-sm text-daiblue transition hover:bg-daiblue/10 active:scale-95">
            复制
          </button>
        </div>

        {/* 固定邀请奖励规则 */}
        <div className="rounded-lg border border-cinnabar/30 bg-[#fff5f2] p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="font-serifCn text-lg font-bold text-cinnabar">固定邀请奖励</p>
              <p className="mt-1 text-xs text-zheshi">每成功邀请 1 位新用户，奖励自动到账</p>
            </div>
            <div className="text-right">
              <p className="font-serifCn text-3xl font-black text-cinnabar">+{rewardQuota} 次</p>
              <p className="text-xs text-zheshi">使用额度</p>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-4 rounded-lg bg-white/70 px-4 py-2 text-sm text-ink">
            <span>
              已成功邀请 <b className="text-cinnabar">{invitedCount}</b> 人
            </span>
            <span>累计奖励 <b>{invitedCount * rewardQuota}</b> 次</span>
          </div>
        </div>
      </div>
    </div>
  );
}
