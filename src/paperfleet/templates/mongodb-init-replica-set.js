/* eslint-disable no-undef */
// Reproduced from upstream Overleaf CE:
// https://github.com/overleaf/overleaf/blob/main/bin/shared/mongodb-init-replica-set.js
rs.initiate({ _id: 'overleaf', members: [{ _id: 0, host: 'mongo:27017' }] })
