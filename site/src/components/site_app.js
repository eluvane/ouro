import { Jqhtml_Component } from '@jqhtml/core';

import { site_config } from '../site.config.js';
import SiteAppTemplate from './site_app.jqhtml';

class SiteApp extends Jqhtml_Component {
  static component_name = 'Site_App';

  on_create() {
    this.args.site = site_config;
  }
}

export const components = [SiteAppTemplate, SiteApp];
