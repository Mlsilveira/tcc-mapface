"""Mostra o que há no banco, de dentro da própria aplicação.

**Por que isto existe.** O RDS vive numa sub-rede sem rota para a internet, com
`publicly_accessible = false` e um security group que só aceita o grupo da task
do ECS. Não há como abrir um cliente SQL do notebook de ninguém — e isso é o
desenho, não um obstáculo acidental: um banco com dados comportamentais de
estudantes não deve ser alcançável da mesa de quem quer que seja.

O que sobra é perguntar de dentro. Este script roda como uma task avulsa do ECS,
com a mesma imagem, as mesmas credenciais e a mesma rede do backend, e escreve o
resultado no CloudWatch.

**Ele não mostra senha nem hash.** Mostra quem existe, quando entrou e o que
cada um produziu — que é o que se quer saber ao conferir se o deploy pegou. O
hash é inútil para diagnóstico e perigoso num log que fica guardado.

Uso, a partir de `infra/`:

    aws ecs run-task --cluster mapface-poc --task-definition mapface-poc-backend \\
      --launch-type FARGATE --network-configuration ... \\
      --overrides '{"containerOverrides":[{"name":"backend",
                    "command":["python","-m","scripts.inspecionar_banco"]}]}'
"""
from sqlmodel import Session, func, select

from app.database import engine
from app.models import Aluno, BlocoEstudo, LogEngajamento, ResumoSessao, SessaoEstudo


def _linha(rotulo: str, valor) -> None:
    print(f"  {rotulo:.<34} {valor}")


def main() -> None:
    with Session(engine) as db:
        alunos = db.exec(select(Aluno).order_by(Aluno.id)).all()
        sessoes = db.exec(select(SessaoEstudo).order_by(SessaoEstudo.id)).all()
        n_pontos = db.exec(select(func.count()).select_from(LogEngajamento)).one()
        n_blocos = db.exec(select(func.count()).select_from(BlocoEstudo)).one()
        n_resumos = db.exec(select(func.count()).select_from(ResumoSessao)).one()

        print("=" * 62)
        print("BANCO DO MAPFACE")
        print("=" * 62)
        _linha("alunos", len(alunos))
        _linha("sessoes de estudo", len(sessoes))
        _linha("pontos na serie", n_pontos)
        _linha("blocos declarados", n_blocos)
        _linha("resumos congelados", n_resumos)

        print()
        print("ALUNOS  (sem senha nem hash, de proposito)")
        print("-" * 62)
        if not alunos:
            print("  nenhum — o banco esta vazio")
        for aluno in alunos:
            print(f"  #{aluno.id}  {aluno.nome}  <{aluno.email}>")

        print()
        print("SESSOES")
        print("-" * 62)
        if not sessoes:
            print("  nenhuma")
        for sessao in sessoes:
            pontos = db.exec(
                select(func.count())
                .select_from(LogEngajamento)
                .where(LogEngajamento.id_sessao == sessao.id)
            ).one()
            com_sonolencia = db.exec(
                select(func.count())
                .select_from(LogEngajamento)
                .where(LogEngajamento.id_sessao == sessao.id)
                .where(LogEngajamento.sonolencia.is_not(None))
            ).one()
            fim = sessao.fim.strftime("%d/%m %H:%M") if sessao.fim else "em andamento"
            print(
                f"  #{sessao.id}  aluno {sessao.id_aluno}  "
                f"{sessao.inicio.strftime('%d/%m %H:%M')} -> {fim}  "
                f"metodo={sessao.metodo or '-'}  "
                f"pontos={pontos}  com_sonolencia={com_sonolencia}"
            )

        print()
        print("=" * 62)


if __name__ == "__main__":
    main()
