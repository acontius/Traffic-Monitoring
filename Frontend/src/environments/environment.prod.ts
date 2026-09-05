export const environment = {
  production: true,
  apiBaseUrl: '/api',
  wsLiveUrl: `ws${location.protocol === 'https:' ? 's' : ''}://${location.host}/api/ws/live`,
};
