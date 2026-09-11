// biome-ignore lint/nursery/noRestrictedDependencies: JQHTML boots through jQuery
// biome-ignore lint/style/useNamingConvention: $ is the jQuery binding JQHTML init expects
import $ from 'jquery/dist/jquery.slim.js';
import { Jqhtml_Component } from '@jqhtml/core';

import '../docs.css';
import '../docs-layout.css';
import '../docs-content.css';
import { site_config } from '../site.config.js';
import DocumentationAppTemplate from './documentation_app.jqhtml';
import FeatureReferenceTemplate from './feature_reference.jqhtml';
import ProjectFooterTemplate from './project_footer.jqhtml';
import ProjectIntroductionTemplate from './project_introduction.jqhtml';
import QuickStartGuideTemplate from './quick_start_guide.jqhtml';

class DocumentationApp extends Jqhtml_Component {
  static component_name = 'Documentation_App';

  on_create() {
    this.args.site = site_config;
  }

  on_ready() {
    this.sync_active_link();

    $(document).on('keydown', (event) => this.handle_shortcut(event));
    $(globalThis).on('hashchange', () => this.sync_active_link());
  }

  toggle_navigation() {
    const is_open = !this.$.hasClass('navigation-open');

    this.$.toggleClass('navigation-open', is_open);
    this.$sid('menu_toggle').attr('aria-expanded', String(is_open));
  }

  close_navigation() {
    this.$.removeClass('navigation-open');
    this.$sid('menu_toggle').attr('aria-expanded', 'false');
  }

  search_docs(event) {
    this.apply_search(event.currentTarget.value);
  }

  apply_search(raw_query) {
    const query = raw_query.trim().toLowerCase();
    const sections = this.$.find('[data-search-section]');
    let visible_count = 0;

    sections.each((_, section) => {
      const searchable_text = section.textContent.toLowerCase();
      const is_visible = query.length === 0 || searchable_text.includes(query);

      $(section).prop('hidden', !is_visible);
      visible_count += is_visible;
    });

    this.$.find('[data-search-link]').each((_, link) => {
      const [target] = this.$.find(link.hash);
      const link_matches = link.textContent.toLowerCase().includes(query);

      $(link).prop('hidden', target.hidden && !link_matches);
    });

    let status = '';
    if (query.length > 0) {
      let noun = 'sections';
      if (visible_count === 1) {
        noun = 'section';
      }
      status = `${visible_count} ${noun}`;
    }

    this.$sid('empty_state').prop('hidden', query.length === 0 || visible_count > 0);
    this.$sid('search_status').text(status);
  }

  handle_shortcut(event) {
    if (event.key === '/' && !(event.target instanceof HTMLInputElement)) {
      event.preventDefault();
      this.$sid('search_input').trigger('focus');
    }

    if (event.key === 'Escape') {
      this.$sid('search_input').val('');
      this.apply_search('');
      this.close_navigation();
    }
  }

  sync_active_link() {
    let current_hash = globalThis.location.hash;
    if (current_hash.length === 0) {
      current_hash = '#introduction';
    }
    this.$
      .find('[data-nav-link]')
      .removeClass('is-active')
      .removeAttr('aria-current')
      .filter(`[href="${current_hash}"]`)
      .addClass('is-active')
      .attr('aria-current', 'page');
  }
}

export const components = [
  FeatureReferenceTemplate,
  ProjectFooterTemplate,
  ProjectIntroductionTemplate,
  QuickStartGuideTemplate,
  DocumentationAppTemplate,
  DocumentationApp,
];
