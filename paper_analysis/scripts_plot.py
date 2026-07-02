import pandas as pd, matplotlib.pyplot as plt
from pathlib import Path
out=Path('figures'); out.mkdir(exist_ok=True)
plt.style.use('seaborn-v0_8-whitegrid')
# data
k=pd.read_csv('data/k_clusters_trajectory.csv')
r=pd.read_csv('data/rii_trajectory.csv')
s=pd.read_csv('data/specialist_fitness.csv')
c=pd.read_csv('data/collapse_timing.csv')
sel=['exp1_cell3','exp1_cell3_v17','exp1_cell3_v18','exp1_cell3_v19','exp7c_uniform','exp2_b1','exp2_b3']
labels={'exp1_cell3':'spontaneous default','exp1_cell3_v17':'v17.1 force','exp1_cell3_v18':'v18 mild','exp1_cell3_v19':'v19 milder','exp7c_uniform':'Exp7C uniform','exp2_b1':'b1 no-crossover soft','exp2_b3':'b3 no-mutation soft'}
# fig2 K trajectories
fig,ax=plt.subplots(figsize=(6.5,3.2))
for v in sel:
    d=k[k.variant==v]
    if len(d): ax.plot(d.gen,d.K_clusters,marker='o',label=labels.get(v,v),linewidth=1.8)
ax.set_xlabel('Generation'); ax.set_ylabel('RCC clusters K'); ax.set_title('Compatibility-cluster trajectories')
ax.set_ylim(0.8,5.3); ax.legend(fontsize=7,ncol=2,frameon=True)
fig.tight_layout(); fig.savefig(out/'fig2_k_clusters.png',dpi=220); plt.close(fig)
# fig3 RII trajectories
fig,ax=plt.subplots(figsize=(6.5,3.2))
for v in sel:
    d=r[r.variant==v]
    if len(d): ax.plot(d.gen,d.RII_mean,marker='o',label=labels.get(v,v),linewidth=1.8)
ax.axhline(0.25,color='gray',linestyle='--',linewidth=1,label='RII=0.25')
ax.set_xlabel('Generation'); ax.set_ylabel('RII'); ax.set_title('Reproductive isolation trajectories')
ax.set_ylim(-0.03,1.05); ax.legend(fontsize=7,ncol=2,frameon=True)
fig.tight_layout(); fig.savefig(out/'fig3_rii.png',dpi=220); plt.close(fig)
# fig4 specialist fitness selected variants
fig,ax=plt.subplots(figsize=(6.5,3.2))
for v in ['exp1_5_high_migration','exp1_cell3_v15','exp1_cell3_v16']:
    d=s[s.variant==v]
    if len(d):
        # plot max across niches per gen and maybe by niche for high migration only
        g=d.groupby('gen').F_mean.max().reset_index()
        ax.plot(g.gen,g.F_mean,linewidth=1.5,label=v)
ax.set_xlabel('Generation'); ax.set_ylabel('Max matched-niche mean fitness'); ax.set_title('Phenotypic specialist fitness persists')
ax.legend(fontsize=7,frameon=True); fig.tight_layout(); fig.savefig(out/'fig4_specialist_fitness.png',dpi=220); plt.close(fig)
# fig5 collapse timing
cc=c[c.gen_first_collapse.notna()].copy()
fig,ax=plt.subplots(figsize=(6.5,3.0))
colors=['#4C78A8' if v!='exp1_cell3_v17' else '#59A14F' for v in cc.variant]
ax.bar(range(len(cc)),cc.gen_first_collapse, color=colors)
ax.set_xticks(range(len(cc))); ax.set_xticklabels(cc.variant,rotation=35,ha='right',fontsize=8)
ax.set_ylabel('First collapse generation'); ax.set_title('Collapse timing for runs with initial isolation')
ax.axhspan(18,20,color='orange',alpha=0.18,label='18--20 gen')
ax.legend(fontsize=8); fig.tight_layout(); fig.savefig(out/'fig5_collapse_timing.png',dpi=220); plt.close(fig)
