import jqhtml from '@jqhtml/vite-plugin';

// GitHub project Pages live at /ouro/. A later custom domain should build
// with SITE_BASE=/ and a CNAME in site/public/.
const base = process.env.SITE_BASE || '/ouro/';

export default {
  base,
  appType: 'mpa',
  plugins: [jqhtml()],
  build: {
    rollupOptions: {
      input: ['index.html', 'docs/index.html'],
    },
  },
};
