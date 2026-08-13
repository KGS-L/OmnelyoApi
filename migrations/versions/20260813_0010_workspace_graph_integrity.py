"""enforce workspace integrity across the content graph

Revision ID: 20260813_0010
Revises: 20260813_0009
"""
from alembic import op

revision = "20260813_0010"
down_revision = "20260813_0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM videos child
                JOIN videos parent ON parent.id = child.parent_video_id
                WHERE child.workspace_id <> parent.workspace_id
            ) OR EXISTS (
                SELECT 1 FROM jobs j JOIN videos v ON v.id = j.video_id
                WHERE j.workspace_id <> v.workspace_id
            ) OR EXISTS (
                SELECT 1 FROM channels c
                JOIN social_connections s ON s.id = c.connection_id
                WHERE c.workspace_id <> s.workspace_id OR c.platform <> s.platform
            ) OR EXISTS (
                SELECT 1 FROM publications p JOIN videos v ON v.id = p.video_id
                WHERE p.workspace_id <> v.workspace_id
            ) OR EXISTS (
                SELECT 1 FROM publications p JOIN channels c ON c.id = p.channel_id
                WHERE p.workspace_id <> c.workspace_id
            ) OR EXISTS (
                SELECT 1 FROM publications p JOIN jobs j ON j.id = p.job_id
                WHERE p.workspace_id <> j.workspace_id
            ) THEN
                RAISE EXCEPTION 'Le graphe métier contient des références entre workspaces'
                    USING ERRCODE = '23514';
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_video_workspace_integrity() RETURNS trigger AS $$
        BEGIN
            IF NEW.parent_video_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM videos parent
                WHERE parent.id = NEW.parent_video_id
                  AND parent.workspace_id = NEW.workspace_id
            ) THEN
                RAISE EXCEPTION 'Le parent vidéo appartient à un autre workspace'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_videos_workspace_integrity
        BEFORE INSERT OR UPDATE OF workspace_id, parent_video_id ON videos
        FOR EACH ROW EXECUTE FUNCTION enforce_video_workspace_integrity();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_job_workspace_integrity() RETURNS trigger AS $$
        BEGIN
            IF NEW.video_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM videos v
                WHERE v.id = NEW.video_id AND v.workspace_id = NEW.workspace_id
            ) THEN
                RAISE EXCEPTION 'La vidéo du job appartient à un autre workspace'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_jobs_workspace_integrity
        BEFORE INSERT OR UPDATE OF workspace_id, video_id ON jobs
        FOR EACH ROW EXECUTE FUNCTION enforce_job_workspace_integrity();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_channel_workspace_integrity() RETURNS trigger AS $$
        BEGIN
            IF NEW.connection_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM social_connections s
                WHERE s.id = NEW.connection_id
                  AND s.workspace_id = NEW.workspace_id
                  AND s.platform = NEW.platform
            ) THEN
                RAISE EXCEPTION 'La connexion sociale de la chaîne est incompatible'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_channels_workspace_integrity
        BEFORE INSERT OR UPDATE OF workspace_id, connection_id, platform ON channels
        FOR EACH ROW EXECUTE FUNCTION enforce_channel_workspace_integrity();
        """
    )
    op.execute(
        """
        CREATE FUNCTION enforce_publication_workspace_integrity() RETURNS trigger AS $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM videos v
                WHERE v.id = NEW.video_id AND v.workspace_id = NEW.workspace_id
            ) OR NOT EXISTS (
                SELECT 1 FROM channels c
                WHERE c.id = NEW.channel_id AND c.workspace_id = NEW.workspace_id
            ) OR (NEW.job_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM jobs j
                WHERE j.id = NEW.job_id AND j.workspace_id = NEW.workspace_id
            )) THEN
                RAISE EXCEPTION 'La publication référence un autre workspace'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER trg_publications_workspace_integrity
        BEFORE INSERT OR UPDATE OF workspace_id, video_id, channel_id, job_id ON publications
        FOR EACH ROW EXECUTE FUNCTION enforce_publication_workspace_integrity();
        """
    )


def downgrade():
    for table, trigger, function in (
        ("publications", "trg_publications_workspace_integrity", "enforce_publication_workspace_integrity"),
        ("channels", "trg_channels_workspace_integrity", "enforce_channel_workspace_integrity"),
        ("jobs", "trg_jobs_workspace_integrity", "enforce_job_workspace_integrity"),
        ("videos", "trg_videos_workspace_integrity", "enforce_video_workspace_integrity"),
    ):
        op.execute(f"DROP TRIGGER {trigger} ON {table}")
        op.execute(f"DROP FUNCTION {function}()")
