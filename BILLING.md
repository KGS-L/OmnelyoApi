# Facturation indépendante des prestataires

`BillingService` est l'unique point d'entrée métier. L'API web ne doit jamais
appeler directement Dodo Payments, PayDunya, Paddle ou Orange Money.

## Flux commun

```text
Plan interne
   -> BillingService.start_checkout()
   -> PaymentProvider.create_checkout()
   -> paiement pending
   -> validation manuelle ou webhook signé
   -> paiement paid
   -> crédits ajoutés ou abonnement activé
```

Les montants sont stockés sous forme d'entiers dans la plus petite unité de la
devise. Pour le XOF, qui n'a pas de centimes usuels, `2000` représente 2 000 FCFA.

## Mode manuel du MVP

Le fournisseur `manual` renvoie les instructions Mobile Money et une référence
UUID obligatoire. Après vérification du transfert, un administrateur appelle
`confirm_manual_payment(payment_id, transaction_reference)`. Cette opération est
transactionnelle et idempotente : une double validation n'ajoute pas deux fois
les crédits.

Ne jamais activer automatiquement un achat sur la seule base d'une capture
d'écran envoyée par le client. La référence doit être contrôlée dans le compte
marchand Orange Money/Moov Money.

## Webhooks automatiques

Un futur adaptateur doit implémenter :

- `create_checkout()` ;
- `parse_webhook()`, incluant obligatoirement la vérification cryptographique de
  la signature du fournisseur.

`BillingService.handle_webhook()` vérifie ensuite l'idempotence de l'événement,
le montant et la devise avant d'accorder le produit. L'enregistrement du webhook
et l'attribution sont effectués dans la même transaction.

## Migration PostgreSQL

Les tables SQLite préparent le domaine, mais `workspace_id` n'a volontairement
pas encore de clé étrangère. Lors de la migration PostgreSQL, il deviendra une FK
vers `workspaces.id`, les identifiants deviendront des UUID natifs et les
opérations `BEGIN IMMEDIATE` seront remplacées par des verrous de lignes.

## Prochains adaptateurs

1. Dodo Payments pour les abonnements et paiements internationaux.
2. PayDunya pour Orange Money/Moov Money en XOF.
3. Paddle en solution de secours Merchant of Record.
