# Roadmap & Actions

---

## 🔴 Avant tout push public (bloquant)

- [X] Documenter explicitement dans `README.md` et `docs\REVERSE_ENGINEERING.md` que `PRIVATE_KEY` est extraite du binaire public distribué par WA Conception (pas un secret de notre conception)
- [ ] Créer `docs/LEGAL.md` — cadre légal français (Art. L.122-6-1 CPI, Directive 2009/24/CE, CJUE C-406/10), voir aussi https://www.app.asso.fr/centre-information/base-de-connaissances/code-logiciels/les-contrats/contrat-de-licence-dutilisation-logiciel-proprietaire 

> D. Décompilation du logiciel à des fins d’interopérabilité
> Selon l’article L122-6-1 IV du code de la propriété intellectuelle qui transpose l’article 6 de la directive 2009/24/CE, « la reproduction du code du logiciel ou la traduction de la forme de ce code n’est pas soumise à l’autorisation de l’auteur lorsque la reproduction ou la traduction au sens du 1° ou du 2° de l’article L. 122-6 est indispensable pour obtenir les informations nécessaires à l’interopérabilité d’un logiciel créé de façon indépendante avec d’autres logiciels, sous réserve que soient réunies les conditions suivantes :
> * ces actes sont accomplis par la personne ayant le droit d’utiliser un exemplaire du logiciel ou pour son compte par une personne habilitée à cette fin ;
> * les informations nécessaires à l’interopérabilité n’ont pas déjà été rendues facilement et rapidement accessibles aux personnes mentionnées au 1° ci-dessus ;
> * et ces actes sont limités aux parties du logiciel d’origine nécessaires à cette interopérabilité ».
> L’article ajoute que « les informations ainsi obtenues ne peuvent être :

> * ni utilisées à des fins autres que la réalisation de l’interopérabilité du logiciel créé de façon indépendante ;
> * ni communiquées à des tiers sauf si cela est nécessaire à l’interopérabilité du logiciel créé de façon indépendante ;
> * ni utilisées pour la mise au point, la production ou la commercialisation d’un logiciel dont l’expression est substantiellement similaire ou pour tout autre acte portant atteinte au droit d’auteur».
> Selon le considérant n°10 de la directive 2009/24/CE, « un programme d’ordinateur est appelé à communiquer et à fonctionner avec d’autres éléments d’un système informatique et avec des utilisateurs […] Cette interconnexion et cette interaction fonctionnelles sont communément appelées « interopérabilité » ; cette interopérabilité peut être définie comme étant la capacité d’échanger des informations et d’utiliser mutuellement les informations échangées ».

> En d’autres termes, l’interopérabilité est la possibilité pour différents programmes de communiquer entre eux, d’échanger des informations dans un environnement déterminé. Pour permettre cette interopérabilité, il faut connaître le code source des interfaces logiques permettant la communication. La décompilation désigne la reconstitution du code source du logiciel destinée à isoler les interfaces logiques et à les adapter.

> La décompilation d’un logiciel est donc autorisée à des fins d’interopérabilité et par l’utilisateur, qui a acquis de manière légitime le logiciel. Tel n’était pas le cas de M. T qui avait travaillé sur une version du logiciel « tombée du camion ». La cour d’appel de Paris a jugé que « la pratique du désassemblage d’un logiciel n’est licite que dans les strictes hypothèses prévues par l’article L 122-6-1-IV du code de la propriété intellectuelle mais constitue une contrefaçon dès lors que, comme en l’espèce, l’auteur de la manipulation, non titulaire des droits d’utilisation, n’agit pas à des fins d’interopérabilité et met à disposition de tiers (les internautes) les informations obtenues » (Reproduction d’un logiciel sans autorisation, arrêt du 21 février 2006).


---

## 🟠 Sécurité & qualité code (court terme)

TODO

---

## 🟡 Documentation & GitHub Pages

- [ ] Créer `CONTRIBUTING.md`
- [ ] Créer `CHANGELOG.md`
- [X] Créer `docs\REVERSE_ENGINEERING.md`
- [ ] Configurer GitHub Pages (MkDocs recommandé) avec la structure :
  - `index.md` — présentation + screenshots
  - `protocol.md` — protocole BLE module On.e
  - `reverse/` — méthodologie RE
  - `legal.md` — cadre légal français
  - `install.md` — guide d'installation
  - `api.md` — référence API HTTP + ZMQ


---

## 🟢 Publication du plugin Homebridge

- [ ] Vérifier syntaxe : `node --check integrations/homebridge/homebridge-on.e/index.js`
- [ ] Vérifier que `config.schema.json` couvre tous les paramètres
- [ ] Ajouter des tests (même minimalistes)
- [ ] Publier sur npm : `npm publish --access public` depuis `integrations/homebridge/homebridge-on.e/`
- [ ] Soumettre au registre [Homebridge Verified Plugins](https://github.com/homebridge/homebridge/wiki/Verified-Plugins)
