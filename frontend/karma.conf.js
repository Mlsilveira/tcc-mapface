// Usa o Chromium que vem com o puppeteer para a suíte não depender de um
// navegador instalado na máquina (nem localmente, nem em CI).
// computeExecutablePath é síncrono; puppeteer.executablePath() devolve uma
// Promise, que o karma não sabe esperar.
process.env.CHROME_BIN = require('@puppeteer/browsers').computeExecutablePath({
  browser: 'chrome',
  buildId: require('puppeteer').PUPPETEER_REVISIONS.chrome,
  cacheDir: require('path').join(require('os').homedir(), '.cache', 'puppeteer'),
});

module.exports = function (config) {
  config.set({
    basePath: '',
    frameworks: ['jasmine', '@angular-devkit/build-angular'],
    plugins: [
      require('karma-jasmine'),
      require('karma-chrome-launcher'),
      require('karma-jasmine-html-reporter'),
      require('karma-coverage'),
      require('@angular-devkit/build-angular/plugins/karma'),
    ],
    client: {
      jasmine: {},
      clearContext: false,
    },
    jasmineHtmlReporter: {
      suppressAll: true,
    },
    coverageReporter: {
      dir: require('path').join(__dirname, './coverage/frontend'),
      subdir: '.',
      reporters: [{ type: 'html' }, { type: 'text-summary' }],
    },
    reporters: ['progress', 'kjhtml'],
    port: 9876,
    colors: true,
    logLevel: config.LOG_INFO,
    autoWatch: true,
    browsers: ['ChromeHeadless'],
    singleRun: true,
    restartOnFileChange: true,
  });
};
