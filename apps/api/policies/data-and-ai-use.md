# Data and AI use policy

> SIMULATED COMPANY POLICY, written for the ChainPilot demo. It is not the policy of any real company.

Version 1, 2026-10-17.

## Data labels

ChainPilot uses three kinds of data, and every screen and answer must say which one it shows:

- Simulated operations (SYN- codes): products, warehouses, stock, suppliers and purchase orders invented by the seed generator.
- M5 (Walmart) public sales data: used to train and test the demand forecasts.
- Olist (Brazilian marketplace) public order data: used to train and test the delivery-risk model.

The public datasets describe different businesses. Their records are never joined with each other or with the simulated data as if they were the same company. The demand of a simulated product is borrowed from the forecast of one linked M5 item; this is a labelled demo link, not the same product.

## Public datasets

The public datasets are used under their own terms, are downloaded by the owner, and are not stored in the code repository. Model results are reported as measured, including weak ones.

## AI copilot limits

The AI copilot reads data through fixed read-only tools and answers with citations to the records and policy sections it used. It does not calculate stock levels or order quantities itself; those numbers come from the system's tested calculations. It cannot approve, order, move stock or change any data, and it says so when asked. If the data needed for an answer is missing, it says that instead of guessing.
