import {mkdir,readFile,writeFile,copyFile} from 'node:fs/promises';
const [html,worker]=await Promise.all([readFile('index.html','utf8'),readFile('worker/index.mjs','utf8')]);
await Promise.all(['dist/server','dist/.openai','dist/drizzle'].map(path=>mkdir(path,{recursive:true})));
await Promise.all([
  writeFile('dist/server/index.js','const PAGE='+JSON.stringify(html)+';\n'+worker),
  copyFile('.openai/hosting.json','dist/.openai/hosting.json'),
  copyFile('drizzle/0000_school.sql','dist/drizzle/0000_school.sql')
]);
