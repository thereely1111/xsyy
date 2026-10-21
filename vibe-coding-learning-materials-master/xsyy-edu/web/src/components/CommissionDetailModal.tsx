import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { useAppStore } from '../store/appStore';
import type { CommissionRecordItem, WithdrawalRecordItem } from '../types';

function fenToYuan(fen: number): string {
  return ((fen || 0) / 100).toFixed(2);
}

function formatTime(value: string | null): string {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString('zh-CN', { hour12: false });
}

const LEVEL_LABEL: Record<number, string> = { 1: '直接邀请' };
const WITHDRAWAL_STATUS_LABEL: Record<string, string> = {
  pending: '审核中',
  approved: '已通过',
  rejected: '已驳回',
};

export function CommissionDetailModal() {
  const open = useAppStore((s) => s.commissionModalOpen);
  const closeCommissionModal = useAppStore((s) => s.closeCommissionModal);
  const summary = useAppStore((s) => s.commissionSummary);
  const authToken = useAppStore((s) => s.authToken);
  const refreshCommission = useAppStore((s) => s.refreshCommission);
  const addToast = useAppStore((s) => s.addToast);

  const [records, setRecords] = useState<CommissionRecordItem[]>([]);
  const [recordsTotal, setRecordsTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [recordsLoading, setRecordsLoading] = useState(false);
  const [withdrawals, setWithdrawals] = useState<WithdrawalRecordItem[]>([]);
  const [withdrawAmount, setWithdrawAmount] = useState('');
  const [withdrawing, setWithdrawing] = useState(false);

  useEffect(() => {
    if (!open || !authToken) return;
    setPage(1);
    setWithdrawAmount('');
    void loadRecords(authToken, 1);
    void loadWithdrawals(authToken);
    void refreshCommission();
  }, [open, authToken]);

  const loadRecords = async (token: string, targetPage: number) => {
    setRecordsLoading(true);
    try {
      const result = await api.getCommissionRecords(token, targetPage, 20);
      setRecords(result.items);
      setRecordsTotal(result.total);
      setPage(targetPage);
    } catch (error) {
      addToast((error as Error).message, 'error');
    } finally {
      setRecordsLoading(false);
    }
  };

  const loadWithdrawals = async (token: string) => {
    try {
      const result = await api.getCommissionWithdrawals(token);
      setWithdrawals(result.items);
    } catch {
      // 静默失败
    }
  };

  const totalPages = Math.max(1, Math.ceil(recordsTotal / 20));

  const submitWithdraw = async () => {
    if (!authToken) {
      addToast('请先登录', 'error');
      return;
    }
    const yuan = Number(withdrawAmount);
    if (!Number.isFinite(yuan) || yuan < 1) {
      addToast('请输入有效的提现金额（最低 1 元）', 'error');
      return;
    }
    setWithdrawing(true);
    try {
      const result = await api.withdrawCommission(authToken, Math.round(yuan * 100));
      addToast(result.message || '提现申请已提交', 'success');
      setWithdrawAmount('');
      await refreshCommission();
      await loadWithdrawals(authToken);
      await loadRecords(authToken, page);
    } catch (error) {
      addToast((error as Error).message, 'error');
    } finally {
      setWithdrawing(false);
    }
  };

  if (!open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[1500] flex items-center justify-center bg-black/55 p-4">
      <div className="flex max-h-[90vh] w-full max-w-2xl flex-col rounded-2xl border border-zheshi/35 bg-[#f8f2e7f6] p-6 shadow-neo backdrop-blur">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-serifCn text-2xl font-black text-daiblue">返利明细</h3>
          <button
            type="button"
            onClick={closeCommissionModal}
            className="rounded-lg border border-daiblue/30 px-3 py-1.5 text-sm text-daiblue transition hover:bg-white/70"
          >
            关闭
          </button>
        </div>

        {/* 可提现返利总额 */}
        <section className="rounded-xl border border-cinnabar/30 bg-[#fff5f2] p-4">
          <p className="text-sm text-zheshi">当前累计可提现返利</p>
          <p className="mt-1 font-serifCn text-3xl font-black text-cinnabar">
            ¥{fenToYuan(summary?.availableAmount ?? 0)}
          </p>
          <div className="mt-3 grid grid-cols-3 gap-3 text-center">
            <div className="rounded-lg bg-white/70 p-2">
              <p className="text-xs text-zheshi">累计返利</p>
              <p className="text-sm font-bold text-ink">¥{fenToYuan(summary?.totalReward ?? 0)}</p>
            </div>
            <div className="rounded-lg bg-white/70 p-2">
              <p className="text-xs text-zheshi">提现中</p>
              <p className="text-sm font-bold text-ink">¥{fenToYuan(summary?.pendingAmount ?? 0)}</p>
            </div>
            <div className="rounded-lg bg-white/70 p-2">
              <p className="text-xs text-zheshi">已提现</p>
              <p className="text-sm font-bold text-ink">¥{fenToYuan(summary?.withdrawnAmount ?? 0)}</p>
            </div>
          </div>
        </section>

        {/* 提现申请 */}
        <section className="mt-4 rounded-xl border border-daiblue/20 bg-white/75 p-4">
          <h4 className="font-serifCn text-lg font-bold text-daiblue">申请提现</h4>
          <div className="mt-2 flex items-center gap-2">
            <input
              type="number"
              min="1"
              step="0.01"
              value={withdrawAmount}
              onChange={(e) => setWithdrawAmount(e.target.value)}
              placeholder="输入提现金额（元）"
              className="w-48 rounded-lg border border-daiblue/25 bg-white px-3 py-2 text-sm outline-none ring-daiblue/30 focus:ring"
            />
            <button
              type="button"
              disabled={withdrawing}
              onClick={() => void submitWithdraw()}
              className="rounded-lg bg-cinnabar px-4 py-2 text-sm font-semibold text-white transition hover:brightness-95 disabled:opacity-60"
            >
              {withdrawing ? '提交中...' : '提交提现申请'}
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
          <p className="mt-2 text-xs text-zheshi">提现申请提交后需管理员审核，最低提现金额 1 元。</p>
        </section>

        {/* 提现记录 */}
        {withdrawals.length > 0 ? (
          <section className="mt-4 rounded-xl border border-daiblue/20 bg-white/75 p-4">
            <h4 className="font-serifCn text-lg font-bold text-daiblue">提现记录</h4>
            <ul className="mt-2 max-h-28 space-y-1 overflow-y-auto text-sm">
              {withdrawals.map((item) => (
                <li key={item.requestId} className="flex items-center justify-between gap-2 rounded-lg bg-white/70 px-3 py-1.5">
                  <span className="text-ink">¥{fenToYuan(item.amount)}</span>
                  <span className="text-zheshi">{formatTime(item.createdAt)}</span>
                  <span
                    className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                      item.status === 'approved'
                        ? 'bg-jade/15 text-jade'
                        : item.status === 'rejected'
                          ? 'bg-cinnabar/10 text-cinnabar'
                          : 'bg-[#e6a23c]/15 text-[#c47f17]'
                    }`}
                  >
                    {WITHDRAWAL_STATUS_LABEL[item.status] || item.status}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        {/* 返利来源明细 */}
        <section className="mt-4 flex min-h-0 flex-1 flex-col rounded-xl border border-daiblue/20 bg-white/75 p-4">
          <div className="flex items-center justify-between">
            <h4 className="font-serifCn text-lg font-bold text-daiblue">返利来源明细</h4>
            <span className="text-xs text-zheshi">共 {recordsTotal} 笔</span>
          </div>
          <div className="mt-2 min-h-0 flex-1 overflow-y-auto">
            {recordsLoading ? (
              <p className="py-6 text-center text-sm text-zheshi">加载中...</p>
            ) : records.length === 0 ? (
              <p className="py-6 text-center text-sm text-zheshi">暂无返利记录，快去邀请好友吧</p>
            ) : (
              <ul className="space-y-2">
                {records.map((record) => (
                  <li key={record.id} className="flex items-center justify-between gap-3 rounded-lg bg-white/70 px-3 py-2">
                    <div className="min-w-0">
                      <p className="truncate text-sm text-ink">
                        来源用户：<span className="font-semibold">{record.sourceUsername || record.sourceUserId}</span>
                      </p>
                      <p className="mt-0.5 text-xs text-zheshi">
                        {LEVEL_LABEL[record.level] || '直接邀请'}
                        {record.inviterUsername ? `（直接邀请者：${record.inviterUsername}）` : ''}
                        · {formatTime(record.createdAt)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="font-bold text-cinnabar">+¥{fenToYuan(record.amount)}</p>
                      <p className="text-xs text-zheshi">{record.status === 'withdrawn' ? '已提现' : '可提现'}</p>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
          {totalPages > 1 ? (
            <div className="mt-3 flex items-center justify-center gap-3 text-sm">
              <button
                type="button"
                disabled={page <= 1 || recordsLoading}
                onClick={() => authToken && void loadRecords(authToken, page - 1)}
                className="rounded-lg border border-daiblue/25 px-3 py-1 text-daiblue transition hover:bg-white disabled:opacity-40"
              >
                上一页
              </button>
              <span className="text-zheshi">{page} / {totalPages}</span>
              <button
                type="button"
                disabled={page >= totalPages || recordsLoading}
                onClick={() => authToken && void loadRecords(authToken, page + 1)}
                className="rounded-lg border border-daiblue/25 px-3 py-1 text-daiblue transition hover:bg-white disabled:opacity-40"
              >
                下一页
              </button>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}
