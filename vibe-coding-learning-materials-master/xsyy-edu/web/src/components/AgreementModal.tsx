import type { AgreementDocType } from '../types';
import { AGREEMENT_LAST_UPDATED, AGREEMENT_VERSION, useAppStore } from '../store/appStore';

const USER_AGREEMENT_TEXT = `《象数演易用户协议》
版本号：${AGREEMENT_VERSION}
最后更新：${AGREEMENT_LAST_UPDATED}

欢迎使用“象数演易”服务。请您在注册、登录及使用服务前仔细阅读并理解本协议。

一、账号管理
1. 用户应妥善保管账号信息与登录凭证，并对账号下的一切操作承担责任。
2. 用户不得利用平台实施违法违规行为，不得发布侵犯他人合法权益的内容。
3. 用户有权申请注销账号。账号注销后，平台将按规则删除或匿名化您的个人数据，且该操作不可撤销。

二、使用规范
1. 用户应遵守中华人民共和国现行法律法规及公序良俗。
2. 用户不得通过技术手段干扰平台正常运行，不得恶意刷量、批量爬取或攻击系统。

三、内容与版权
1. 用户在平台生成或发布的内容，知识产权归用户所有。
2. 为实现产品运营与展示功能，用户授予平台在服务范围内的非独占展示与传播权。
3. 用户应确保其发布内容不侵犯第三方权益，如产生纠纷由用户自行承担责任。

四、免责声明
1. 平台将尽力保障服务稳定，但不承诺服务绝对不中断、无错误或完全满足特定需求。
2. 因不可抗力、网络故障、第三方服务异常等原因导致的损失，平台在法律允许范围内不承担间接损失责任。

五、协议变更与适用法律
1. 平台可根据业务发展对本协议进行更新，并通过适当方式提示。
2. 本协议的订立、执行与争议解决均适用中华人民共和国法律。`;

const PRIVACY_POLICY_TEXT = `《象数演易隐私政策》
版本号：${AGREEMENT_VERSION}
最后更新：${AGREEMENT_LAST_UPDATED}

本政策用于说明平台如何收集、使用、存储与保护您的个人信息。

一、我们收集的信息
1. 账号信息：用户名、手机号（如您提供）等。
2. 设备信息：设备标识、登录环境等，用于账号安全与设备绑定管理。
3. 使用记录：题目输入、生成记录、邀请记录、反馈信息、系统交互记录。

二、信息使用目的
1. 用于提供核心功能，包括登录认证、题目生成、次数管理、消息通知与问题反馈处理。
2. 用于产品优化与服务改进，包括故障排查、统计分析和体验优化。
3. 用于安全风控，防止欺诈、滥用和非法访问。

三、信息存储与保护
1. 我们采取合理措施保护您的信息安全，防止未经授权访问、泄露或篡改。
2. 在达到处理目的或您申请注销后，我们将依法删除或匿名化相关个人信息。

四、对外提供
1. 除法律法规要求或为提供服务所必需外，我们不会向无关第三方出售您的个人信息。
2. 在涉及第三方服务时，我们将要求其履行相应的信息保护义务。

五、您的权利
1. 您有权访问、更正、删除您的个人信息。
2. 您有权注销账号并要求删除相关个人数据（法律法规另有规定的除外）。

六、未成年人说明
若您为未成年人，请在监护人同意和指导下使用本服务。

七、法律适用
本政策受中华人民共和国法律管辖。`;

function agreementTitle(docType: AgreementDocType): string {
  return docType === 'user' ? '用户协议' : '隐私政策';
}

function agreementText(docType: AgreementDocType): string {
  return docType === 'user' ? USER_AGREEMENT_TEXT : PRIVACY_POLICY_TEXT;
}

export function AgreementInlineLinks() {
  const openAgreementModal = useAppStore((s) => s.openAgreementModal);

  return (
    <>
      我已阅读并同意
      <button
        type="button"
        onClick={() => openAgreementModal('user')}
        className="mx-1 text-daiblue underline decoration-daiblue/40 underline-offset-2 transition hover:text-cinnabar"
      >
        《用户协议》
      </button>
      和
      <button
        type="button"
        onClick={() => openAgreementModal('privacy')}
        className="ml-1 text-daiblue underline decoration-daiblue/40 underline-offset-2 transition hover:text-cinnabar"
      >
        《隐私政策》
      </button>
    </>
  );
}

export function AgreementModal() {
  const modal = useAppStore((s) => s.agreementModal);
  const closeAgreementModal = useAppStore((s) => s.closeAgreementModal);

  if (!modal.open) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-[1500] flex items-center justify-center bg-black/55 p-4">
      <div className="w-full max-w-3xl rounded-2xl border border-zheshi/35 bg-[#f8f2e6f5] p-6 shadow-neo backdrop-blur">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-serifCn text-2xl font-black text-daiblue">{agreementTitle(modal.docType)}</h3>
          <button
            type="button"
            onClick={closeAgreementModal}
            className="rounded-lg border border-daiblue/30 px-3 py-1.5 text-sm text-daiblue transition hover:bg-white/70"
          >
            关闭
          </button>
        </div>

        <div className="max-h-[62vh] overflow-y-auto rounded-xl border border-daiblue/15 bg-white/75 p-4">
          <pre className="whitespace-pre-wrap break-words font-sansCn text-sm leading-7 text-ink">{agreementText(modal.docType)}</pre>
        </div>

        <div className="mt-4 text-right">
          <button
            type="button"
            onClick={closeAgreementModal}
            className="rounded-lg bg-daiblue px-5 py-2 font-semibold text-white transition hover:brightness-95"
          >
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
