/**
 * 知识点标签渲染模块（新版：知识域 → 年级 → 章/单元）
 * 使用原有分类的彩色标签样式（.tag.tag-main / .tag.tag-sub）渲染知识点标签
 *
 * 显示规则（单标签组）：
 *   知识域 → 主标签（大方块，.tag.tag-main）
 *   年级 + 章/单元 → 副标签（.tag.tag-sub，两个小长方形）
 *   知识点标签（模块级，sub_tags）→ 不显示（隐性属性）
 *
 * 颜色映射：按年级（18个）区分颜色，主副标签同色
 * （章/单元共38个，颜色需求过多，故按年级着色）
 */
(function (global) {
    "use strict";

    /**
     * 年级 → CSS颜色类型映射
     * 8 个年级各对应一种独立颜色
     * CSS 类名定义于 css/version-colors.css
     */
    var GRADE_COLOR_MAP = {
        "一上": "cyan",
        "一下": "lime",
        "二上": "amber",
        "二下": "pink",
        "三上": "indigo",
        "三下": "slate",
        "四上": "emerald",
        "四下": "fuchsia",
        "五上": "sky",
        "五下": "copper",
        "六上": "teal",
        "六下": "goldenrod",
        "七上": "blue",
        "七下": "royalblue",
        "八上": "purple",
        "八下": "orchid",
        "九上": "red",
        "九下": "olive"
    };

    // 兼容旧引用（原教材版本颜色映射，已废弃）
    var VERSION_COLOR_MAP = GRADE_COLOR_MAP;
    var DOMAIN_COLOR_MAP = GRADE_COLOR_MAP;

    /**
     * 根据年级获取颜色类型
     * 未匹配到年级时回退到 "blue"，避免新标签因字段不匹配全部显示为旧棕色。
     */
    function getColorTypeByGrade(grade) {
        if (!grade) return "blue";
        return GRADE_COLOR_MAP[grade] || "blue";
    }

    // 兼容旧函数名（现按年级取色，传入年级）
    function getColorTypeByVersion(grade) {
        return getColorTypeByGrade(grade);
    }

    // 兼容旧函数名（现按年级取色，传入年级）
    function getColorTypeByDomain(grade) {
        return getColorTypeByGrade(grade);
    }

    /**
     * HTML 转义
     */
    function escapeHtml(text) {
        if (!text) return "";
        var div = document.createElement("div");
        div.textContent = String(text);
        return div.innerHTML;
    }

    /**
     * 标准化 knowledge_tags 为单标签组格式
     * 兼容旧数据：数组格式取第一组；对象格式直接使用
     */
    function normalizeToSingle(knowledgeTags) {
        if (!knowledgeTags) return null;
        if (Array.isArray(knowledgeTags)) {
            for (var i = 0; i < knowledgeTags.length; i++) {
                if (knowledgeTags[i] && knowledgeTags[i].main_tag) {
                    return knowledgeTags[i];
                }
            }
            return null;
        }
        if (knowledgeTags.version || knowledgeTags.main_tag) {
            return knowledgeTags;
        }
        return null;
    }

    /**
     * 渲染知识点标签 HTML（使用原有 .tag 样式，单标签组，按年级着色）
     * @param {Object|Array} knowledgeTags - { version(知识域), grade, main_tag(章/单元), sub_tags } 或旧数组格式
     * @param {Object} options - { containerClass: 'tag-container' | 'masonry-card-tags' }
     * @returns {string} HTML 字符串
     */
    function renderHTML(knowledgeTags, options) {
        // 标准化为单标签组（旧多标签组数据只取第一组）
        var kt = normalizeToSingle(knowledgeTags);
        if (!kt || !kt.main_tag) return "";

        var opts = options || {};
        var containerClass = opts.containerClass || "tag-container";
        var parts = [];

        var domain = kt.version || "";
        var grade = kt.grade || "";
        var mainTag = kt.main_tag || "";
        var colorType = getColorTypeByGrade(grade);

        // 知识域 → 主标签（大方块）
        if (domain) {
            parts.push(
                '<span class="tag tag-main ' + colorType + '">' +
                escapeHtml(domain) +
                "</span>"
            );
        }

        // 年级 → 副标签
        if (grade) {
            parts.push(
                '<span class="tag tag-sub ' + colorType + '">' +
                escapeHtml(grade) +
                "</span>"
            );
        }

        // 章/单元 → 副标签
        if (mainTag) {
            parts.push(
                '<span class="tag tag-sub ' + colorType + '">' +
                escapeHtml(mainTag) +
                "</span>"
            );
        }

        // 知识点标签（模块级）为隐性属性，不显示

        if (parts.length === 0) {
            return "";
        }

        return '<div class="' + containerClass + '">' + parts.join("") + "</div>";
    }

    /**
     * 渲染到指定容器
     */
    function render(container, knowledgeTags, options) {
        if (container) {
            container.innerHTML = renderHTML(knowledgeTags, options);
        }
    }

    /**
     * 构建“第二标签”的“+”悬停切换标记 HTML。
     * 常态只显示主标签；仅在标签组存在第二标签时，主标签后追加一个“+”标记，
     * 悬停（hover）或聚焦（键盘）时展开显示第二标签组。
     * @param {Object|null} second - 第二标签组 {version, grade, main_tag, sub_tags}
     * @returns {string}
     */
    function buildSecondToggleHTML(second) {
        if (!second || !second.main_tag) return "";
        var sColor = getColorTypeByGrade(second.grade);
        var parts = [];
        if (second.version) parts.push('<span class="tag tag-main ' + sColor + '">' + escapeHtml(second.version) + "</span>");
        if (second.grade) parts.push('<span class="tag tag-sub ' + sColor + '">' + escapeHtml(second.grade) + "</span>");
        parts.push('<span class="tag tag-sub ' + sColor + '">' + escapeHtml(second.main_tag) + "</span>");
        return (
            '<span class="tag-second-toggle" tabindex="0" role="button" aria-label="查看第二标签">' +
            '<span class="tag-second-plus">+</span>' +
            '<span class="tag-second-pop">' + parts.join("") + "</span>" +
            "</span>"
        );
    }

    /**
     * 渲染含“第二标签 + 号”的标签组 HTML。
     * 常态仅显示主标签组；若存在第二标签组，则在主标签后追加“+”，悬停展开第二标签。
     *
     * @param {Object|Array} knowledgeTags - 主标签组（兼容旧数组/对象）
     * @param {Object|null} secondTag - 第二标签组
     * @param {Object} options - { containerClass }
     * @returns {string} HTML 字符串
     */
    function renderWithSecond(knowledgeTags, secondTag, options) {
        var kt = normalizeToSingle(knowledgeTags);
        var opts = options || {};
        var containerClass = opts.containerClass || "tag-container";

        if (!kt || !kt.main_tag) {
            // 异常兜底：仅第二标签存在时，直接以“+”形式呈现
            if (secondTag && secondTag.main_tag) {
                return '<div class="' + containerClass + '">' + buildSecondToggleHTML(secondTag) + "</div>";
            }
            return "";
        }

        var domain = kt.version || "";
        var grade = kt.grade || "";
        var mainTag = kt.main_tag || "";
        var colorType = getColorTypeByGrade(grade);
        var parts = [];
        if (domain) parts.push('<span class="tag tag-main ' + colorType + '">' + escapeHtml(domain) + "</span>");
        if (grade) parts.push('<span class="tag tag-sub ' + colorType + '">' + escapeHtml(grade) + "</span>");
        if (mainTag) parts.push('<span class="tag tag-sub ' + colorType + '">' + escapeHtml(mainTag) + "</span>");

        var toggle = buildSecondToggleHTML(secondTag);
        return '<div class="' + containerClass + '">' + parts.join("") + toggle + "</div>";
    }

    // 导出
    global.KnowledgeTagRender = {
        renderHTML: renderHTML,
        render: render,
        renderWithSecond: renderWithSecond,
        buildSecondToggleHTML: buildSecondToggleHTML,
        getColorTypeByGrade: getColorTypeByGrade,
        getColorTypeByVersion: getColorTypeByVersion,
        getColorTypeByDomain: getColorTypeByDomain,
        GRADE_COLOR_MAP: GRADE_COLOR_MAP,
        DOMAIN_COLOR_MAP: DOMAIN_COLOR_MAP,
        VERSION_COLOR_MAP: VERSION_COLOR_MAP
    };

    // 兼容旧引用
    global.KnowledgeTags = {
        renderHTML: function (knowledgeTags, options) {
            var newOpts = { containerClass: "masonry-card-tags" };
            return renderHTML(knowledgeTags, newOpts);
        },
        render: render
    };
})(window);
