import { useState } from 'react';
import { useAppStore } from '../store/appStore';

function fenToYuan(fen: number | undefined): string {
  return ((fen || 0) / 100).toFixed(2);
}

export function AccountCenterModal() {
  const open = useAppStore((s) => s.accountCenterOpen);
  const closeAccountCenter = useAppStore((s) => s.closeAccountCenter);
  const deleteAccount = useAppStore((s) => s.deleteAccount);
  const openCommissionModal = useAppStore((s) => s.openCommissionModal);
  const commissionSummary = useAppStore((s) => s.commissionSummary);

  const [confirmDeleting, setConfirmDeleting] = useState(false);
  const [deleting, setDeleting] = useState(false);

  if (!open) {
    return null;
  }

  const onDelete = async () => {
    setDeleting(true);
    await deleteAccount();
    setDeleting(false);
    setConfirmDeleting(false);
  };

  return (
    <div className="fixed inset-0 z-[1400] flex items-center justify-center bg-black/55 p-4">
      <div className="w-full max-w-xl rounded-2xl border border-zheshi/35 bg-[#f8f2e7f6] p-6 shadow-neo backdrop-blur">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-serifCn text-2xl font-black text-daiblue">个人中心</h3>
          <button
            type="button"
            onClick={closeAccountCenter}
            className="rounded-lg border border-daiblue/30 px-3 py-1.5 text-sm text-daiblue transition hover:bg-white/70"
          >
            关闭
          </button>
        </div>

        {/* 返利模块 */}
        <section className="rounded-xl border border-cinnabar/30 bg-[#fff5f2] p-4">
          <div className="flex items-center justify-between">
            <h4 className="font-serifCn text-lg font-bold text-cinnabar">我的返利</h4>
            <button
              type="button"
              onClick={() => void openCommissionModal()}
              className="rounded-lg border border-cinnabar/45 px-3 py-1 text-sm font-semibold text-cinnabar transition hover:bg-cinnabar/10"
            >
              返利明细
            </button>
          </div>
          <p className="mt-2 text-sm text-zheshi">当前累计可提现返利</p>
          <p className="mt-1 font-serifCn text-3xl font-black text-cinnabar">
            ¥{fenToYuan(commissionSummary?.availableAmount)}
          </p>
          <div className="mt-3 grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg bg-white/70 p-2">
              <p className="text-xs text-zheshi">累计返利</p>
              <p className="text-sm font-bold text-ink">¥{fenToYuan(commissionSummary?.totalReward)}</p>
            </div>
            <div className="rounded-lg bg-white/70 p-2">
              <p className="text-xs text-zheshi">提现中</p>
              <p className="text-sm font-bold text-ink">¥{fenToYuan(commissionSummary?.pendingAmount)}</p>
            </div>
            <div className="rounded-lg bg-white/70 p-2">
              <p className="text-xs text-zheshi">已提现</p>
              <p className="text-sm font-bold text-ink">¥{fenToYuan(commissionSummary?.withdrawnAmount)}</p>
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              onClick={() => void openCommissionModal()}
              className="rounded-lg bg-cinnabar px-4 py-2 text-sm font-semibold text-white transition hover:brightness-95"
            >
              申请提现
            </button>
            <button
              type="button"
              onClick={() => {
                window.location.href = 'user_interface.html#recharge';
              }}
              className="rounded-lg border border-[#e6a23c]/60 bg-gradient-to-b from-[#fdf6ec] to-[#f5e6c8] px-4 py-2 text-sm font-semibold text-daiblue transition hover:brightness-95"
            >
              充值
            </button>
          </div>
          <p className="mt-2 text-xs text-zheshi">邀请好友注册并填写您的邀请码，即可获得返利；返利支持提现与充值。</p>
        </section>

        <section className="mt-4 rounded-xl border border-daiblue/20 bg-white/75 p-4">
          <h4 className="font-serifCn text-lg font-bold text-daiblue">账号安全</h4>
          <p className="mt-2 text-sm text-zheshi">修改密码</p>
          <p className="mt-1 text-xs text-zheshi">如需修改密码，请在现有密码校验通过后更新。</p>
        </section>

        <section className="mt-4 rounded-xl border border-cinnabar/30 bg-[#fff5f2] p-4">
          <h4 className="font-serifCn text-lg font-bold text-cinnabar">注销账号</h4>
          <p className="mt-2 text-sm text-zheshi">注销后所有个人数据将被永久删除，无法恢复。</p>

          {!confirmDeleting ? (
            <button
              type="button"
              onClick={() => setConfirmDeleting(true)}
              className="mt-3 rounded-lg border border-cinnabar/45 px-4 py-2 font-semibold text-cinnabar transition hover:bg-cinnabar/10"
            >
              注销账号
            </button>
          ) : (
            <div className="mt-3 rounded-lg border border-cinnabar/30 bg-white/80 p-3">
              <p className="text-sm text-ink">确定要注销账号吗？此操作将清除您的次数余额、返利、邀请记录等。操作不可逆。</p>
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  disabled={deleting}
                  onClick={() => void onDelete()}
                  className="rounded-lg bg-cinnabar px-4 py-2 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-60"
                >
                  {deleting ? '处理中...' : '确认注销'}
                </button>
                <button
                  type="button"
                  disabled={deleting}
                  onClick={() => setConfirmDeleting(false)}
                  className="rounded-lg border border-daiblue/30 px-4 py-2 text-sm text-daiblue transition hover:bg-white"
                >
                  取消
                </button>
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
